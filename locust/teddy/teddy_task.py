import functools
import inspect
import logging
import time
from typing import Type, Callable, cast

import locust
from .teddy_log import teddy_logger
from .teddy_session import TeddySession
from .. import User
from ..exception import (
    InterruptTaskSet,
    RescheduleTaskImmediately,
    RescheduleTask)
from ..user.task import TaskSet, TaskSetMeta

from .teddy_def import TeddyInfo, TeddyType, TeddyCfg, TeddyMsgType
from .teddy_exception import (
    TeddyException,
    Teddy_InvalidTaskOrder,
    Teddy_InvalidTaskSet)

"""Teddy Task类型"""
TeddyTaskT = Callable[..., None]


class TeddyTaskSetMeta(TaskSetMeta):
    """
    Teddy任务集元类, 用于提取指定Teddy任务集中的所有任务
    Note: TeddyTaskSetMeta忽略TaskSetMeta内部的收集(已不再需要)
    """
    def __new__(mcs, classname, bases, class_dict):
        # 收集tasks, 并按order排序
        teddy_tasks: [TeddyTaskT] = []
        for item in class_dict.values():
            if ('teddy_info' in dir(item) and
                    item.teddy_info['teddy_type'] == TeddyType.Task):
                teddy_tasks.append(item)
        teddy_tasks = sorted(teddy_tasks, key=lambda x: x.teddy_info['order'])

        task_orders = set()
        for task in teddy_tasks:
            task_orders.add(task.teddy_info['order'])

        if len(teddy_tasks) != len(task_orders):
            raise TeddyException(f"Some task(s) order are repeated, taskset: {classname}")

        # 放到class_dict
        class_dict['tasks'] = teddy_tasks

        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTaskSet(TaskSet, metaclass=TeddyTaskSetMeta):
    # region __init__
    def __init__(self, top_taskset: TaskSet) -> None:
        super().__init__(top_taskset)
        self._task_index = -1
    # endregion

    # region properties
    @property
    def session(self) -> TeddySession:
        """获取session对象"""
        return self.user.session
    # endregion

    # region taskset事件方法定义
    def on_init(self):
        """事件方法, user创建时调用, 生命周期内只会调用一次"""
        pass

    def on_destroy(self):
        """事件方法, user销毁时调用, 生命周期内只会调用一镒"""
        pass
    # endregion

    # region task/taskset操作
    def get_cur_task(self):
        """获取当前task"""
        if self._task_index == -1:
            return None
        return self.tasks[self._task_index]

    def get_taskset(self, taskset_cls_or_name: Type[TaskSet] | str) -> TaskSet | None:
        """获取指定任务集"""
        return self.user.get_taskset(taskset_cls_or_name)
    # endregion

    # region report支持
    def report_send(self, msg_id: int, msg_size: int) -> None:
        """
        报告 已发送指定bytes数据
        :param msg_id: 消息Id
        :param msg_size: 已发送的消息字节数
        """
        self._report_send_or_recv(TeddyMsgType.Send, msg_id, msg_size)

    def report_recv(self, msg_id: int, msg_size: int, status: int) -> None:
        """
        报告 已接收指定bytes数据
        :param msg_id: 消息Id
        :param msg_size: 已接收的消息字节数
        :param status: 消息状态码
        """
        self._report_send_or_recv(TeddyMsgType.Recv, msg_id, msg_size, status)

    def report_send_and_recv(self,
                             send_msg_id: int,
                             send_msg_size: int,
                             recv_msg_id: int,
                             recv_msg_size: int,
                             recv_msg_status: int,
                             cost_time: float):
        """
        报告一次send_and_recv, teddy内部将识别为Paired Message
        :param send_msg_id: 发送Message Id
        :param send_msg_size: 发送Message Size
        :param recv_msg_id: 接收Message Id
        :param recv_msg_size: 接收Message Size
        :param recv_msg_status: 接收Message Status
        : param cost_time: 耗时, 秒为单位
        """
        assert self.parent.get_cur_taskset() is self
        cur_task = self.get_cur_task()
        assert cur_task is not None

        # 记录于teddy_info
        teddy_info: TeddyInfo = cur_task.teddy_info
        teddy_info['paired_msgs'].append({
            'send_msg_id': send_msg_id,
            'send_msg_size': send_msg_size,
            'recv_msg_id': recv_msg_id,
            'recv_msg_size': recv_msg_size,
            'recv_msg_status': recv_msg_status,
            'cost_time': cost_time,
        })

        # 上报到统计图表
        locust.events.send_and_recv_msg.fire(send_msg_id=send_msg_id,
                                             send_msg_size=send_msg_size,
                                             recv_msg_id=recv_msg_id,
                                             recv_msg_size=recv_msg_size,
                                             recv_msg_status=recv_msg_status,
                                             cost_time=cost_time)

    def report_fail(self, fail_desc: Exception | str, stop_user_after_report: bool=False) -> None:
        """
        报告失败, 一个task一次只允许报告一个失败, task执行中如多次调用, 将保留最后一次
        :param fail_desc: 失败描述
        :param stop_user_after_report: 是否在报告失败后, stop user, 默认False
        """
        assert self.parent.get_cur_taskset() is self
        cur_task = self.get_cur_task()
        assert cur_task is not None

        # 记录于teddy_info
        teddy_info: TeddyInfo = cast(TeddyInfo, cur_task.teddy_info)
        teddy_info['fail'] = fail_desc
        teddy_info['stop_user_after_fail'] = stop_user_after_report
    # endregion

    # region jump支持
    def jump_to_task(self, task_order: int | Callable[..., None], immediately: bool = True) -> None:
        """
        跳转到指定任务
        :param task_order: (optional) 任务顺序
        :param immediately: (optional) 是否立即跳转
        """
        self.parent.jump_to_task(task_order, immediately)

    def jump_to_taskset(self, taskset_cls_or_name: Type[TaskSet] | str,
                        task_order: int = -1,
                        immediately: bool = True) -> None:
        """
        跳转到指定任务集
        :param taskset_cls_or_name: (required) 任务集名字或任务集类
        :param task_order: (optional): 任务顺序, 如为-1, 将使用目标任务集的第一个任务
        :param immediately: (optional): 是否立即跳转
        """
        self.parent.jump_to_taskset(taskset_cls_or_name, task_order, immediately)
    # endregion

    # region 日志输出支持
    def log(self, log_level: int, msg: object):
        """输出log"""
        teddy_logger.log(log_level, f'{self}: {msg}')

    def logd(self, msg: object):
        """输出debug log"""
        self.log(logging.DEBUG, msg)

    def logi(self, msg: object):
        """输出info log"""
        self.log(logging.INFO, msg)

    def logw(self, msg: object):
        """输出warn log"""
        self.log(logging.WARNING, msg)

    def loge(self, msg: object):
        """输出error log"""
        self.log(logging.ERROR, msg)

    def logf(self, msg: object):
        """输出fatal log"""
        self.log(logging.FATAL, msg)
    # endregion

    # region __str__
    def __str__(self):
        return f'{self.user}.{self.__class__.__name__}'
    # endregion

    # region 内部实现
    def get_next_task(self):
        self._task_index = (self._task_index + 1) % len(self.tasks)
        return self.tasks[self._task_index]

    def _locate_task(self, task_order):
        """定位task order"""
        for task_idx in range(len(self.tasks)):
            if self.tasks[task_idx].teddy_info['order'] == task_order:
                return task_idx
        return -1

    def _report_send_or_recv(self,
                             msg_type: int,
                             msg_id: int,
                             msg_size: int,
                             status: int = 0):
        assert self.parent.get_cur_taskset() is self
        cur_task = self.get_cur_task()
        assert cur_task is not None

        # 记录于teddy_info
        teddy_info: TeddyInfo = cur_task.teddy_info
        msgs_key = 'send_msgs' if msg_type == TeddyMsgType.Send else 'recv_msgs'
        teddy_info[msgs_key].append({
            'msg_type': msg_type,
            'msg_id': msg_id,
            'msg_len': msg_size,
            'status': 0,
        })

        bytes_key = 'total_send_bytes' if msg_type == TeddyMsgType.Send else 'total_recv_bytes'
        teddy_info[bytes_key] += msg_size

        # 上报到统计图表
        if msg_type == TeddyMsgType.Send:
            locust.events.send_msg.fire(msg_id=msg_id, msg_size=msg_size, status=status)
        else:
            locust.events.recv_msg.fire(msg_id=msg_id, msg_size=msg_size, status=status)

    def _report_task_exec_finish(self, task):
        # 统计耗时
        task_teddy_info: TeddyInfo = task.teddy_info
        cost_time = time.perf_counter() - task_teddy_info['beg_exec_time']

        # Log
        teddy_logger.debug(f'{self}: Task {task.__name__} exec completed, cost time: {round(cost_time, 6)}')

        # 执行统计上报
        fail = task_teddy_info['fail']
        request_meta = {
            'request_type': self.teddy_info['desc'],
            'name': task.teddy_info['desc'],
            'response_time': round(cost_time * 1000),
            'request_length': task_teddy_info['total_send_bytes'],
            'response_length': task_teddy_info['total_recv_bytes'],
            'exception': fail,
        }
        locust.events.request.fire(**request_meta)

        # 确认是否停止user
        if (fail is not None and
                task_teddy_info['stop_user_after_fail']):
            self.user.stop(True)
    # endregion


class TeddyTopTaskSetMeta(TaskSetMeta):
    """Teddy顶层任务集元类"""
    def __new__(mcs, classname, bases, class_dict):
        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTopTaskSet(TaskSet, metaclass=TeddyTopTaskSetMeta):
    def __init__(self, user: User) -> None:
        super().__init__(user)
        self._taskset_index = -1
        self._taskset_insts = [taskset(self) for taskset in user.tasks]
        self._updatable_taskset_insts = [taskset for taskset in self._taskset_insts if hasattr(taskset, 'on_update')]

    @property
    def tasksets(self) -> [TeddyTaskSet]:
        """取得所有taskset实例"""
        return self._taskset_insts

    def get_cur_taskset(self) -> TeddyTaskSet | None:
        """
        获取当前任务集
        :return: 当前任务对象, 如不存在或未启动, 返回None
        """
        if self._taskset_index == -1:
            return None
        return self._taskset_insts[self._taskset_index]

    def get_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str) -> TeddyTaskSet | None:
        """
        获取指定任务集
        :param taskset_cls_or_name: (optional) 任务集类或类名
        :return: 任务集对象, 如找不到则返回空
        """
        for taskset in self._taskset_insts:
            if isinstance(taskset_cls_or_name, str):
                if taskset.__class__.__name__ == taskset_cls_or_name:
                    return taskset
            elif (issubclass(taskset_cls_or_name, TeddyTaskSet) and
                    taskset.__class__ == taskset_cls_or_name):
                return taskset
        return None

    def jump_to_task(self, task_order: int | Callable[..., None], immediately: bool = True) -> None:
        """
        跳转到指定任务
        :param task_order: (required) 任务编号
        :param immediately: (optional) 是否立刻跳转, 即不sleep
        """
        # 定位task
        if callable(task_order):
            task_order = task_order.teddy_info['order']

        taskset = self.get_cur_taskset()
        task_idx = taskset._locate_task(task_order)
        if task_idx == -1:
            raise Teddy_InvalidTaskOrder(f'Invalid task order, taskset: {taskset}, order: {task_order}')

        # 上报当前task执行信息
        cur_task = taskset.get_cur_task()
        taskset._report_task_exec_finish(cur_task)

        # 更新task索引信息
        taskset._task_index = task_idx
        del taskset._task_queue[:]
        taskset._task_queue.append(taskset.tasks[task_idx])

        # Log
        task = taskset.tasks[task_idx]
        teddy_logger.debug(f'{self.user}: Jump to task: '
                           f'{taskset.__class__.__name__}.{task.__name__}({task.teddy_info["order"]})')

        # 执行切换
        if immediately:
            raise RescheduleTaskImmediately()
        else:
            raise RescheduleTask()

    def jump_to_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str,
                        task_order: int = -1,
                        immediately: bool = True) -> None:
        """
        跳转到指定任务集
        :param taskset_cls_or_name: (required) 任务集名字或类
        :param task_order: (optional) 任务编号
        :param immediately: (optional) 是否立刻跳转, 即不sleep
        """
        # 定位taskset
        taskset_idx = self._locate_taskset(taskset_cls_or_name)
        if taskset_idx == -1:
            raise Teddy_InvalidTaskSet(f'Invalid taskset: {taskset_cls_or_name}')

        # 定位task
        task_idx = 0
        taskset = self._taskset_insts[taskset_idx]
        if task_order != -1:
            task_idx = taskset._locate_task(task_order)
        if task_idx == -1:
            raise Teddy_InvalidTaskOrder(f'Invalid task order, '
                                         f'taskset: {taskset_cls_or_name}, order: {task_order}')

        # 上报当前task执行信息
        cur_taskset = self.get_cur_taskset()
        cur_task = cur_taskset.get_cur_task()
        cur_taskset._report_task_exec_finish(cur_task)

        # 更新taskset索引信息+队列信息
        taskset._task_index = task_idx
        del taskset._task_queue[:]
        taskset._task_queue.append(taskset.tasks[task_idx])

        # 更新top taskset索引信息+队列信息
        self._taskset_index = taskset_idx
        del self._task_queue[:]
        self._task_queue.append(taskset)

        # Log
        task = taskset.tasks[task_idx]
        teddy_logger.debug(f'{self.user}: Jump to taskset: '
                           f'{taskset.__class__.__name__}.{task.__name__}({task.teddy_info["order"]})')

        # 执行切换
        raise InterruptTaskSet(reschedule=immediately)

    def get_next_task(self):
        self._taskset_index = (self._taskset_index + 1) % len(self._taskset_insts)
        return self._taskset_insts[self._taskset_index]

    def execute_task(self, task):
        task.run()

    def _locate_taskset(self, taskset_cls_or_name) -> int:
        """定位taskset"""
        if isinstance(taskset_cls_or_name, str):
            taskset_name = taskset_cls_or_name
        elif (inspect.isclass(taskset_cls_or_name) and
                issubclass(taskset_cls_or_name, TeddyTaskSet)):
            taskset_name = taskset_cls_or_name.__name__
        else:
            return -1

        for taskset_idx in range(len(self._taskset_insts)):
            if self._taskset_insts[taskset_idx].__class__.__name__ == taskset_name:
                return taskset_idx

        return -1


def teddy_task(task_order: int, /, *, task_desc: str | None = None) -> TeddyTaskT:
    """
    Teddy任务注解
    :param task_order: (required) 任务顺序, 即此任务在一个任务集中的执行顺序, 要求>=0
    :param task_desc: (optional) 任务描述(剪短)
    :return: 一个generator对象
    """
    def generator(task):
        # @teddy_task不允许装饰: 事件方法, run方法, 及非_开始的方法(即teddy task必须是protected/private)
        if task.__name__.startswith('on_'):
            raise TeddyException(f'@teddy_task not allow decorate on_xxx() event method: {task.__name__}')
        if task.__name__ == 'run':
            raise TeddyException(f'@teddy_task not allow decorate run() method: {task.__name__}')
        if not task.__name__.startswith('_'):
            raise TeddyException(
                f'@teddy_task not allow decorate public method(must be started with _): {task.__name__}')
        else:
            # 不允许重复装饰
            if hasattr(task, 'teddy_info'):
                raise ValueError('Not allow repeatedly use @teddy_task/@teddy_taskset annotation')

            # 生成TeddyInfo
            teddy_info: TeddyInfo = cast(TeddyInfo,
                                         {'teddy_type': TeddyType.Task,
                                          'name': task.__name__,
                                          'order': task_order,
                                          'beg_exec_time': 0.0,
                                          'total_send_bytes': 0,
                                          'total_recv_bytes': 0,
                                          'send_msgs': [],
                                          'recv_msgs': [],
                                          'paired_msgs': []})
            teddy_info['desc'] = task_desc if task_desc else teddy_info['name'][1:]
            teddy_info['desc'] = f'{task_order:03d}-{teddy_info["desc"]}'
            task.teddy_info = teddy_info

            # Log
            teddy_logger.debug(f'Annotate teddy task: {task}, order: {task_order}, desc: {task_desc}')
        return task
    return generator


def teddy_taskset(taskset_desc: str | Type[TeddyTaskSet] = None):
    """
    Teddy任务集注解
    :param taskset_desc: (optional) 任务集描述, 不填充时将表示无参装饰器, 即为taskset class本身
    :return: 一个generator对象
    """
    def generator(taskset_cls: Type[TeddyTaskSet]) -> Type[TeddyTaskSet]:
        # 生成'teddy_info'信息
        if hasattr(taskset_cls, 'teddy_info'):
            raise ValueError('Not allow repeatedly use @teddy_task/@teddy_taskset annotation')
        teddy_info: TeddyInfo = cast(TeddyInfo,
                                     {'teddy_type': TeddyType.TaskSet,
                                      'name': taskset_cls.__class__.__name__})
        if taskset_desc:
            teddy_info['desc'] = taskset_desc
        else:
            teddy_info['desc'] = teddy_info['name']
        taskset_cls.teddy_info = teddy_info

        # 处理tasks, 以实现自动化上报(通过teddy_info结构)
        def task_wrapper(task, taskset):
            # 执行user on_update心跳方法调用
            user = taskset.user
            if hasattr(user, 'on_update'):
                user.on_update()
            for updatable_taskset in taskset.parent._updatable_taskset_insts:
                updatable_taskset.on_update()

            # 记录开始执行时间
            task_teddy_info = task.teddy_info
            task_teddy_info['beg_exec_time'] = time.perf_counter()

            # 清理task teddy info中的统计信息
            task_teddy_info['total_send_bytes'] = 0
            task_teddy_info['total_recv_bytes'] = 0
            del task_teddy_info['send_msgs'][:]
            del task_teddy_info['recv_msgs'][:]
            del task_teddy_info['paired_msgs'][:]
            task_teddy_info['fail'] = None
            task_teddy_info['stop_user_after_fail'] = False

            # Log
            teddy_logger.debug(f'{taskset}: Exec task {task.__name__}')

            # 执行
            task(taskset)
            # 上报执行结果
            taskset._report_task_exec_finish(task)

        for task_idx in range(len(taskset_cls.tasks)):
            task = taskset_cls.tasks[task_idx]
            wrapped_task = functools.partial(task_wrapper, task)
            wrapped_task.__name__ = task.__name__
            wrapped_task.teddy_info = getattr(task, 'teddy_info')

            taskset_cls.task = wrapped_task
            taskset_cls.tasks[task_idx] = wrapped_task

        # Log
        teddy_logger.debug(f'Annotate teddy taskset: {taskset_cls}, desc: {taskset_desc}')

        return taskset_cls

    if callable(taskset_desc):
        taskset_c = taskset_desc
        taskset_desc = taskset_c.__class__.__name__
        return generator(cast(Type[TeddyTaskSet], taskset_c))
    else:
        return generator
