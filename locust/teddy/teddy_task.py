# builtin
import functools
import inspect
import logging
import random
import time
from typing import Type, List, cast

# locust
import locust
from .. import User
from ..exception import (
    InterruptTaskSet,
    RescheduleTaskImmediately,
    RescheduleTask)
from ..user.task import TaskSet, TaskSetMeta

# teddy
from .teddy_log import teddy_logger
from .teddy_session import TeddySession
from .teddy_def import (
    TeddyTaskT,
    TeddyInfo,
    TeddyType,
    TeddyMsgType,
    TeddyTaskScheduleMode,
    TeddyTaskSetType)
from .teddy_exception import TeddyException


class TeddyTaskSetMeta(TaskSetMeta):
    """
    Teddy任务集元类, 用于提取指定Teddy任务集中的所有任务
    Note: TeddyTaskSetMeta忽略TaskSetMeta内部的收集(已不再需要)
    """
    def __new__(mcs, classname, bases, class_dict):
        # 收集tasks, 并按order排序
        tasks: [TeddyTaskT] = []
        for item in class_dict.values():
            if ('teddy_info' in dir(item) and
                    item.teddy_info['teddy_type'] == TeddyType.Task):
                tasks.append(item)
        tasks.sort(key=lambda x: x.teddy_info['order'])

        # order重复校验
        if len(tasks) != len(set(task.teddy_info['order'] for task in tasks)):
            raise TeddyException(f"Some task(s) order are repeated, taskset: {classname}")

        # 如tasks为空, 强制构造一个dummy task
        if not tasks:
            def _dummy_task(taskset):
                taskset.logw(f'TaskSet {classname} not schedulable')
            _dummy_task.teddy_info = {
                'teddy_type': TeddyType.Task,
                'order': 1,
                'name': _dummy_task.__name__,
                'desc': f'001-DummyTask',
                'send_msgs': [],
                'recv_msgs': [],
                'paired_msgs': [],
            }
            class_dict['_dummy_task'] = _dummy_task
            tasks.append(_dummy_task)

        # 执行tawk wrap, 以实现动化统计
        def task_wrapper(task, taskset):
            # 执行user on_update心跳方法调用
            user = taskset.user
            if hasattr(user, 'on_update'):
                user.on_update()
            for updatable_taskset in taskset.parent._updatable_tasksets:
                updatable_taskset.on_update()

            # 记录开始执行时间
            task_teddy_info = task.teddy_info
            task_teddy_info['beg_exec_time'] = time.perf_counter()

            # 清理task teddy info中的统计信息
            task_teddy_info['total_send_bytes'] = 0
            task_teddy_info['total_recv_bytes'] = 0
            task_teddy_info['send_msgs'].clear()
            task_teddy_info['recv_msgs'].clear()
            task_teddy_info['paired_msgs'].clear()
            task_teddy_info['fail'] = None
            task_teddy_info['stop_user_after_fail'] = False

            # Log
            taskset.logd(f'Exec task: {task.__name__}({task_teddy_info["order"]})')

            # 执行
            task(taskset)
            # 上报执行结果
            taskset._report_task_exec_finish(task)

        # 逐个task进行wrap(partial), 同时对class_dict中的task实现进行替换
        for task_idx in range(len(tasks)):
            task = tasks[task_idx]
            task.teddy_info['index'] = task_idx

            wrapped_task = functools.partial(task_wrapper, task)
            wrapped_task.__name__ = task.__name__
            wrapped_task.teddy_info = task.teddy_info

            class_dict[task.__name__] = wrapped_task
            tasks[task_idx] = wrapped_task

        # 更新class_dict['tasks']
        class_dict['tasks'] = tasks

        # 确定task调度模式
        if 'task_schedule_mode' not in class_dict:
            class_dict['task_schedule_mode'] = TeddyTaskScheduleMode.Sequential
        task_schedule_mode: TeddyTaskScheduleMode = class_dict['task_schedule_mode']
        if task_schedule_mode not in TeddyTaskScheduleMode:
            raise TeddyException(f'Invalid task schedule mode {task_schedule_mode} in taskset: {classname}')

        # 如未设置独占调度, 设置默认值(默认: False)
        if 'exclusive_schedule' not in class_dict:
            class_dict['exclusive_schedule'] = False

        # 针对"定序调度配置", 标准化fixed_task_list
        if TeddyTaskScheduleMode.is_fixed_schedule_mode(task_schedule_mode):
            if 'fixed_task_list' not in class_dict:
                class_dict['fixed_task_list'] = [task for task in tasks]
            else:
                fixed_task_list = class_dict['fixed_task_list']
                if not isinstance(fixed_task_list, (list, tuple)):
                    raise TeddyException(f'<fixed_task_list> must be of type list or tuple, taskset: {classname}')

                normalized_fixed_task_list = []
                for fixed_task in fixed_task_list:
                    for task in tasks:
                        if (isinstance(fixed_task, int) and
                                fixed_task == task.teddy_info['order']):
                            normalized_fixed_task_list.append(task)
                            break
                        elif (isinstance(fixed_task, str) and
                                fixed_task == task.teddy_info['name']):
                            normalized_fixed_task_list.append(task)
                            break
                        elif (callable(fixed_task) and
                                fixed_task.__name__ == task.teddy_info['name']):
                            normalized_fixed_task_list.append(task)
                            break
                if len(normalized_fixed_task_list) != len(fixed_task_list):
                    raise TeddyException(f'Some tasks in the <fixed_task_list> '
                                         f'are not configured correctly, taskset: {classname}')
                class_dict['fixed_task_list'] = normalized_fixed_task_list

            if not class_dict['fixed_task_list']:
                raise TeddyException(f'<fixed_task_list> config is empty, taskset: {classname}')

        # 生成scheduling_tasks, 以让teddy运行时更好的进行任务调度
        if TeddyTaskScheduleMode.is_fixed_schedule_mode(task_schedule_mode):
            class_dict['scheduling_tasks'] = class_dict['fixed_task_list']
        else:
            class_dict['scheduling_tasks'] = class_dict['tasks']

        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTaskSet(TaskSet, metaclass=TeddyTaskSetMeta):
    # region __init__
    def __init__(self, top_taskset: TaskSet) -> None:
        super().__init__(top_taskset)
        # 当前任务索引
        self._cur_task_index = -1
        # 任务集执行次数(跳出时重置)
        self._exec_times = 0
    # endregion

    # region properties
    @property
    def session(self) -> TeddySession:
        """获取session对象"""
        return cast(TeddySession, getattr(self.user, 'session'))
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
        if self._cur_task_index == -1:
            return None
        return self.__class__.scheduling_tasks[self._cur_task_index]

    def get_taskset(self, taskset_cls_or_name: Type[TaskSet] | str) -> TaskSet | None:
        """获取指定任务集"""
        return self.parent.get_taskset(taskset_cls_or_name)
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
        :param cost_time: 耗时, 秒为单位
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

    def report_fail(self, fail_desc: Exception | str, stop_user_after_report: bool = False) -> None:
        """
        报告失败, 一个task一次只允许报告一个失败, task执行中如多次调用, 将保留最后一次
        :param fail_desc: 失败描述
        :param stop_user_after_report: 是否在报告失败后, stop user, 默认False
        """
        cur_task = self.get_cur_task()
        assert cur_task is not None

        # 记录于teddy_info
        teddy_info: TeddyInfo = cast(TeddyInfo, cur_task.teddy_info)
        teddy_info['fail'] = fail_desc
        teddy_info['stop_user_after_fail'] = stop_user_after_report

        # Log
        self.log(logging.ERROR if stop_user_after_report else logging.WARNING,
                 f'Report fail, fail_desc: {fail_desc}, stop_user_after_report: {stop_user_after_report}')
    # endregion

    # region jump支持
    def jump_to_task(self,
                     task_order_or_task_name_or_task_method: int | str | TeddyTaskT,
                     immediately: bool = True) -> None:
        """
        跳转到指定任务
        :param task_order_or_task_name_or_task_method: (required) 任务编号/任务方法名/任务方法
        :param immediately: (optional) 是否立即跳转
        """
        self._parent.jump_to_task(task_order_or_task_name_or_task_method, immediately)

    def jump_to_taskset(self, taskset_cls_or_taskset_name: Type[TaskSet] | str,
                        task_order_or_task_name_or_task_method: int | str | TeddyTaskT | None = None,
                        immediately: bool = True) -> None:
        """
        跳转到指定任务集
        :param taskset_cls_or_taskset_name: (required) 任务集名字或任务集类
        :param task_order_or_task_name_or_task_method: (required) 任务编号/任务(方法)名/任务方法, 不指定为第一个编号的任务
        :param immediately: (optional) 是否立即跳转
        """
        self._parent.jump_to_taskset(taskset_cls_or_taskset_name,
                                     task_order_or_task_name_or_task_method,
                                     immediately)

    def jump_to_taskset_type(self,
                             taskset_type: TeddyTaskSetType,
                             immediately: bool = True) -> None:
        """
        跳转到指定的任务集类型中(将从此类别的任务集中按调度策略选择一个任务)
        :param taskset_type: 任务集类型
        :param immediately: (optional) 是否立即跳转
        """
        self._parent.jump_to_taskset_type(taskset_type, immediately)
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
        taskset_cls = self.__class__
        scheduling_tasks: List[TeddyTaskT] = taskset_cls.scheduling_tasks
        if TeddyTaskScheduleMode.is_randomomized_schedule_mode(taskset_cls.task_schedule_mode):
            self._cur_task_index = random.randint(0, len(scheduling_tasks) - 1)
        else:
            self._cur_task_index = (self._cur_task_index + 1) % len(scheduling_tasks)
        return scheduling_tasks[self._cur_task_index]

    def execute_next_task(self):
        # 执行
        super().execute_next_task()
        # 如独占调度, 返回(支持对象级别通过重写exclusive_schedule来达到个别user独占/非独占)
        if (self.exclusive_schedule or
                self.user.exclusive_schedule):
            return

        # 非独占调度, 执行任务集调度判断
        self._exec_times += 1
        if self._exec_times >= len(self.__class__.scheduling_tasks):
            self.parent.jump_to_taskset(None,
                                        None,
                                        immediately=False,
                                        report_task_exec_finish=False)

    def _locate_task(self,
                     task_order_or_task_name_or_task_method: int | str | TeddyTaskT) -> int:
        """定位task order"""
        # None, 取第一个task
        taskset_cls = self.__class__
        if task_order_or_task_name_or_task_method is None:
            if TeddyTaskScheduleMode.is_randomomized_schedule_mode(taskset_cls.task_schedule_mode):
                return random.randint(0, len(taskset_cls.scheduling_tasks) - 1)
            else:
                return 0

        # 如 为callable对象(默认为task对象, 不再作校验), 转换为order
        if callable(task_order_or_task_name_or_task_method):
            task_order_or_task_name_or_task_method = \
                task_order_or_task_name_or_task_method.teddy_info['order']

        # task name/task order, 遍历得到task
        if isinstance(task_order_or_task_name_or_task_method, (str, int)):
            scheduling_tasks: List[TeddyTaskT] = taskset_cls.scheduling_tasks
            for task_index in range(len(scheduling_tasks)):
                task = scheduling_tasks[task_index]
                if isinstance(task_order_or_task_name_or_task_method, str):
                    if task.__name__ == task_order_or_task_name_or_task_method:
                        return task_index
                elif task.teddy_info['order'] == task_order_or_task_name_or_task_method:
                    return task_index

        raise TeddyException(f'Not found task <{task_order_or_task_name_or_task_method}> '
                             f'in taskset: {self.__class__.__name__}')

    def _report_send_or_recv(self,
                             msg_type: TeddyMsgType,
                             msg_id: int,
                             msg_size: int,
                             status: int = 0):
        """报告完成了一次send/recv"""
        # 断言将要报告的taskset为当前正在执行的taskset
        assert self.parent.get_cur_taskset() is self
        # 获取当前task并断言
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
        """报告task执行完成"""
        # 统计耗时
        task_teddy_info: TeddyInfo = task.teddy_info
        cost_time = time.perf_counter() - task_teddy_info['beg_exec_time']

        # Log
        fail = task_teddy_info.get('fail')
        self.logd(f'Task exec finished: {task.__name__}, '
                  f'fail: {True if fail else False}, '
                  f'stop_user_after_fail: '
                  f'{True if (fail and task_teddy_info.get("stop_user_after_fail")) else False}, '
                  f'cost time: {round(cost_time, 6)}s')

        # 执行统计上报
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

    def _update_task_index_info(self, task_index: int):
        """更新task索引信息, 在jump_to_task/jump_to_taskset时调用"""
        self._cur_task_index = task_index

        self._task_queue.clear()
        self._task_queue.append(self.__class__.scheduling_tasks[task_index])
    # endregion


class TeddyTopTaskSetMeta(TaskSetMeta):
    """Teddy顶层任务集元类"""
    def __new__(mcs, classname, bases, class_dict):
        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTopTaskSet(TaskSet, metaclass=TeddyTopTaskSetMeta):
    def __init__(self, user: User) -> None:
        super().__init__(user)
        # 任务集列表
        self._tasksets = [taskset(self) for taskset in user.tasks]
        # 有实现on_update的任务集列表(以进行快速的on_update调用)
        self._updatable_tasksets = [taskset for taskset in self._tasksets if hasattr(taskset, 'on_update')]

        # 当前任务集索引
        self._cur_taskset_index = -1
        # 正在调度中的任务集列表(非class)
        self._scheduling_tasksets = []
        # 当前任务集类型
        self._cur_taskset_type: TeddyTaskSetType | None = None
        # 当前任务集调度模式
        self._cur_taskset_schedule_mode: TeddyTaskScheduleMode | None = None

        # 初始化: _cur_taskset_type/_cur_taskset_schedule_mode/_scheduling_taskset_insts
        user_cls = user.__class__
        for taskset_type in TeddyTaskSetType.__members__.values():
            taskset_clses = user_cls.taskset_type_2_schedulable_tasks[taskset_type]
            if taskset_clses:
                self._cur_taskset_type = taskset_type
                self._cur_taskset_schedule_mode = user_cls.taskset_schedule_mode[taskset_type]
                self._update_scheduling_tasksets()
                break

    @property
    def tasksets(self) -> [TeddyTaskSet]:
        """取得所有taskset实例"""
        return self._tasksets

    def get_cur_taskset(self) -> TeddyTaskSet | None:
        """
        获取当前任务集
        :return: 当前任务对象, 如不存在或未启动, 返回None
        """
        if self._cur_taskset_index == -1:
            return None
        return self._scheduling_tasksets[self._cur_taskset_index]

    def get_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str) -> TeddyTaskSet | None:
        """
        获取指定任务集
        :param taskset_cls_or_name: (optional) 任务集类或类名
        :return: 任务集对象, 如找不到则返回空
        """
        for taskset in self._tasksets:
            if isinstance(taskset_cls_or_name, str):
                if taskset.__class__.__name__ == taskset_cls_or_name:
                    return taskset
            elif (issubclass(taskset_cls_or_name, TeddyTaskSet) and
                    taskset.__class__ is taskset_cls_or_name):
                return taskset
        return None

    def jump_to_task(self,
                     task_order_or_task_name_or_task_method: int | str | TeddyTaskT,
                     immediately: bool = True,
                     report_task_exec_finish: bool = True) -> None:
        """
        跳转到指定任务
        :param task_order_or_task_name_or_task_method: (required) 任务编号/任务(方法)名/任务方法
        :param immediately: (optional) 是否立刻跳转, 即不sleep
        :param report_task_exec_finish: (optional) 是否上报任务执行完成, 默认为True
        """
        # 上报当前task执行信息
        taskset = self.get_cur_taskset()
        if report_task_exec_finish:
            cur_task = taskset.get_cur_task()
            taskset._report_task_exec_finish(cur_task)

        # 定位task, 并更新task索引信息+队列信息
        to_task_index = taskset._locate_task(task_order_or_task_name_or_task_method)
        taskset._update_task_index_info(to_task_index)

        # 重置执行次数
        taskset._exec_times = 0

        # Log
        to_task = taskset.__class__.scheduling_tasks[to_task_index]
        taskset.logd(f'Jump to task: {to_task.__name__}({to_task.teddy_info["order"]}), immediately: {immediately}')

        # 执行切换
        if immediately:
            raise RescheduleTaskImmediately()
        else:
            raise RescheduleTask()

    def jump_to_taskset(self, taskset_cls_or_taskset_name: Type[TeddyTaskSet] | str,
                        task_order_or_task_name_or_task_method: int | str | TeddyTaskT | None = None,
                        immediately: bool = True,
                        report_task_exec_finish: bool = True) -> None:
        """
        跳转到指定任务集
        :param taskset_cls_or_taskset_name: (required) 任务集名字或类
        :param task_order_or_task_name_or_task_method: (required) 任务编号/任务(方法)名/任务方法, 不指定为第一个编号的任务
        :param immediately: (optional) 是否立刻跳转, 即不sleep
        :param report_task_exec_finish: (optional) 是否上报任务执行完成, 默认为True
        """
        # 得到当前任务集/当前任务
        cur_taskset = self.get_cur_taskset()

        # 定位目标taskset, 为None时表示执行taskset schedule
        to_taskset_index = -1
        if taskset_cls_or_taskset_name is None:
            to_taskset_index = self._get_next_taskset_index()
            to_taskset = self._scheduling_tasksets[to_taskset_index]
        else:
            to_taskset = self._locate_taskset(taskset_cls_or_taskset_name)

        # 如目标taskset为自身 且 为业务主动调用, 使用jump_to_task()完成跳转
        if to_taskset is cur_taskset and to_taskset_index == -1:
            self.jump_to_task(task_order_or_task_name_or_task_method, immediately, report_task_exec_finish)
            return

        # 重置执行次数, 并上报
        cur_taskset._exec_times = 0
        if report_task_exec_finish:
            cur_task = cur_taskset.get_cur_task()
            cur_taskset._report_task_exec_finish(cur_task)
        # 重置当前taskset中的task索引
        cur_taskset._cur_task_index = -1

        # 更新top taskset中当前taskset相关信息
        if to_taskset_index != -1:  # 由任务集自动调度产生的调用, 已定位到to_taskset_index, 只更新_cur_taskset_index
            self._cur_taskset_index = to_taskset_index
        else:  # 业务主动调用
            # 如目标任务集类型不同, 执行_cur_taskset_type/_cur_taskset_schedule_mode/_scheduling_taskset_indes更新
            user_cls = self.user.__class__
            to_taskset_type: TeddyTaskSetType = to_taskset.__class__.teddy_info['taskset_type']
            if to_taskset_type != cur_taskset.__class__.teddy_info['taskset_type']:
                self._cur_taskset_type = to_taskset_type
                self._cur_taskset_schedule_mode = user_cls.taskset_schedule_mode[self._cur_taskset_type]
                self._update_scheduling_tasksets()

            # 定位到此taskset的index, 并更新_cur_taskset_index
            for taskset_index in range(len(self._scheduling_tasksets)):
                if self._scheduling_tasksets[taskset_index] is to_taskset:
                    to_taskset_index = taskset_index
                    break
            assert to_taskset_index != -1
            self._cur_taskset_index = to_taskset_index

        # 更新taskset执行队列
        self._task_queue.clear()
        self._task_queue.append(to_taskset)

        # 定位task, 并更新task索引信息+队列信息
        to_task_index = to_taskset._locate_task(task_order_or_task_name_or_task_method)
        to_taskset._update_task_index_info(to_task_index)

        # Log
        to_task = to_taskset.scheduling_tasks[to_task_index]
        self.user.logd(f'Jump to taskset: '
                       f'{to_taskset.__class__.__name__}.{to_task.__name__}({to_task.teddy_info["order"]}), '
                       f'immediately: {immediately}')

        # 执行切换
        raise InterruptTaskSet(reschedule=immediately)

    def jump_to_taskset_type(self,
                             taskset_type: TeddyTaskSetType,
                             immediately: bool = True) -> None:
        """
        跳转到指定的任务集类型中(将从此类别的任务集中按调度策略选择一个任务)
        :param taskset_type: 任务集类型, 如果当前已经处于当前任务集, 将不会有任何效果
        :param immediately: (optional) 是否立即跳转
        """
        # 当前正在执行的任务集类型跟要跳转的任务集类型相同, 返回
        cur_taskset: TeddyTaskSet = self.get_cur_taskset()
        if (cur_taskset is not None and
                taskset_type == cur_taskset.teddy_info['taskset_type']):
            return

        # 当前没有正在调度的taskset 或 跳转到不同类型任务集, 切换任务集并进行跳转
        # - 得到user_cls/taskset_schedule_mode
        user_cls = self.user.__class__
        # - 得到taskset classes
        taskset_clses = user_cls.taskset_type_2_schedulable_tasks[taskset_type]
        # - 选中taskset
        taskset_schedule_mode: TeddyTaskScheduleMode = user_cls.taskset_schedule_mode[taskset_type]
        if TeddyTaskScheduleMode.is_randomomized_schedule_mode(taskset_schedule_mode):
            taskset_cls = random.choice(taskset_clses)
        else:
            taskset_cls = taskset_clses[0]

        # - log
        self.user.logd(f'Jump to taskset type: {taskset_type}, '
                       f'immediately: {immediately}, '
                       f'chose taskset: {taskset_cls.__name__}')

        # - jump to taskset
        self.jump_to_taskset(taskset_cls,
                             task_order_or_task_name_or_task_method=None,
                             immediately=immediately)

    def get_next_task(self):
        self._cur_taskset_index = self._get_next_taskset_index()
        return self._scheduling_tasksets[self._cur_taskset_index]

    def execute_task(self, task):
        task.run()

    def _locate_taskset(self, taskset_cls_or_taskset_name) -> TeddyTaskSet:
        """定位taskset"""
        user_cls = self.user.__class__
        if (inspect.isclass(taskset_cls_or_taskset_name) and
                issubclass(taskset_cls_or_taskset_name, TeddyTaskSet) and
                taskset_cls_or_taskset_name in user_cls.tasks):
            taskset_cls_or_taskset_name = taskset_cls_or_taskset_name.__name__

        taskset: TeddyTaskSet | None = None
        if isinstance(taskset_cls_or_taskset_name, str):
            for ts in self._tasksets:
                if ts.__class__.__name__ == taskset_cls_or_taskset_name:
                    taskset = ts
                    break

        if taskset is None:
            raise TeddyException(f'Could not locate taskset, taskset_cls_or_name: {taskset_cls_or_taskset_name}')

        return taskset

    def _get_next_taskset_index(self) -> int:
        """获取下一个任务集索引"""
        if TeddyTaskScheduleMode.is_randomomized_schedule_mode(self._cur_taskset_schedule_mode):
            return random.randint(0, len(self._scheduling_tasksets) - 1)
        else:
            return (self._cur_taskset_index + 1) % len(self._scheduling_tasksets)

    def _update_scheduling_tasksets(self):
        """更新调度中的taskset列表"""
        user_cls = self.user.__class__
        self._scheduling_tasksets.clear()
        taskset_clses = user_cls.taskset_type_2_schedulable_tasks[self._cur_taskset_type]
        for taskset_cls in taskset_clses:
            for taskset in self._tasksets:
                if taskset.__class__ is taskset_cls:
                    self._scheduling_tasksets.append(taskset)
                    break
        assert len(self._scheduling_tasksets) == len(taskset_clses)


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
            # print(f'Annotate teddy task: {task}, order: {task_order}, desc: {task_desc}')
        return task
    return generator


def teddy_taskset(taskset_type: TeddyTaskSetType, /, *, taskset_desc: str | Type[TeddyTaskSet] = None):
    """
    Teddy任务集注解
    :param taskset_type: 任务集类型
    :param taskset_desc: (optional) 任务集描述, 不填充时将表示无参装饰器, 即为taskset class本身
    :return: 一个generator对象
    """
    def generator(taskset_cls: Type[TeddyTaskSet]) -> Type[TeddyTaskSet]:
        # 生成'teddy_info'信息
        if hasattr(taskset_cls, 'teddy_info'):
            raise ValueError('Not allow repeatedly use @teddy_task/@teddy_taskset annotation')
        teddy_info: TeddyInfo = cast(TeddyInfo,
                                     {'teddy_type': TeddyType.TaskSet,
                                      'name': taskset_cls.__name__,
                                      'taskset_type': taskset_type})
        if taskset_desc:
            teddy_info['desc'] = taskset_desc
        else:
            teddy_info['desc'] = teddy_info['name']
        taskset_cls.teddy_info = teddy_info

        # Log
        # print(f'Annotate teddy taskset: {taskset_cls}, desc: {taskset_desc}')
        return taskset_cls

    if callable(taskset_desc):
        taskset_c = taskset_desc
        taskset_desc = taskset_c.__class__.__name__
        return generator(cast(Type[TeddyTaskSet], taskset_c))
    else:
        return generator
