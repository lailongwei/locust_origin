import functools
import inspect
import random
import time
from typing import Type, Callable, cast, Union

import locust
from . import teddy_logger
from .. import User
from ..exception import (
    InterruptTaskSet,
    RescheduleTaskImmediately,
    RescheduleTask)
from ..user.task import TaskSet, TaskSetMeta

from .teddy_def import TeddyInfo, TeddyType, TeddyCfg
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
            raise TeddyException(f"Some task(s) order are repeated, taskset: f{classname}")

        # 放到class_dict
        class_dict['tasks'] = teddy_tasks

        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTaskSet(TaskSet, metaclass=TeddyTaskSetMeta):
    def __init__(self, top_taskset: TaskSet) -> None:
        super().__init__(top_taskset)
        self._task_index = -1

    def on_init(self):
        """事件方法, uer创建时调用"""
        pass

    def on_destroy(self):
        """事件方法, user销毁时调用"""
        pass

    def jump_to_task(self, task_order: int, immediately: bool = True) -> None:
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

    def get_next_task(self):
        self._task_index = (self._task_index + 1) % len(self.tasks)
        return self.tasks[self._task_index]

    def __str__(self):
        return f'{self.user}.{self.__class__.__name__}'

    def _locate_task(self, task_order):
        """定位task order"""
        for task_idx in range(len(self.tasks)):
            if self.tasks[task_idx].teddy_info['order'] == task_order:
                return task_idx

        return -1


class TeddyTopTaskSetMeta(TaskSetMeta):
    """Teddy顶层任务集元类"""
    def __new__(mcs, classname, bases, class_dict):
        return type.__new__(mcs, classname, bases, class_dict)


class TeddyTopTaskSet(TaskSet, metaclass=TeddyTopTaskSetMeta):
    def __init__(self, user: User) -> None:
        super().__init__(user)
        self._taskset_index = -1
        self._taskset_insts = [taskset(self) for taskset in user.tasks]

    @property
    def tasksets(self) -> [TeddyTaskSet]:
        """取得所有taskset实例"""
        return self._taskset_insts

    def get_cur_taskset(self) -> Union[TeddyTaskSet, None]:
        """
        获取当前任务集
        :return: 当前任务对象, 如不存在或未启动, 返回None
        """
        if self._taskset_index == -1:
            return None
        return self._taskset_insts[self._taskset_index]

    def get_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str) -> Union[TeddyTaskSet, None]:
        """
        获取指定任务集
        :param taskset_cls_or_name: (optional) 任务集类或类名
        :return: 任务集对象, 如找不到则返回空
        """
        for taskset in self._taskset_insts:
            if (taskset_cls_or_name is str and
                    taskset.__class__.__name__ == taskset_cls_or_name):
                return taskset
            elif (isinstance(taskset_cls_or_name, TeddyTaskSet) and
                    taskset.__class__ == taskset_cls_or_name):
                return taskset
        return None

    def jump_to_task(self, task_order: int, immediately: bool = True) -> None:
        """
        跳转到指定任务
        :param task_order: (required) 任务编号
        :param immediately: (optional) 是否立刻跳转, 即不sleep
        """
        # 定位task
        taskset = self.get_cur_taskset()
        task_idx = taskset._locate_task(task_order)
        if task_idx == -1:
            raise Teddy_InvalidTaskOrder(f'Invalid task order, taskset: {taskset}, order: {task_order}')

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
        # @teddy_task不允许装饰: 事件方法 及 run方法(warning)
        if task.__name__.startswith('on_'):
            teddy_logger.warning(f'@teddy_task not allow decorate on_xxx() event method: {task.__name__}')
        if task.__name__ == 'run':
            teddy_logger.warning(f'@teddy_task not allow decorate run() method: {task.__name__}')
        else:
            # 不允许重复装饰
            if hasattr(task, 'teddy_info'):
                raise ValueError('Not allow repeatedly use @teddy_task/@teddy_taskset annotation')

            # 生成TeddyInfo
            teddy_info: TeddyInfo = cast(TeddyInfo,
                                         {'teddy_type': TeddyType.Task,
                                          'name': task.__name__,
                                          'order': task_order})
            if task_desc:
                teddy_info['desc'] = task_desc
            else:
                teddy_info['desc'] = teddy_info['name']
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
            beg = time.perf_counter()
            teddy_logger.info(f'Call {task.__name__}, teddy_info: {task.teddy_info}, task_idx: {task_idx}')
            task(taskset)
            request_meta = {
                'request_type': teddy_info['desc'],
                'name': task.teddy_info['desc'],
                'response_time': random.randint(100, 500),
                'response_length': 512,
                'exception': None,
            }
            locust.events.request.fire(**request_meta)

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
