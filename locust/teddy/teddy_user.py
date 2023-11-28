import functools
import time
from typing import Type, Union, Dict

from . import teddy_logger
from ..user.users import UserMeta, User

from .teddy_exception import TeddyException
from .teddy_task import TeddyTaskSet, TeddyTopTaskSet
from .teddy_user_mgr import teddy_user_mgr


class TeddyUserMeta(UserMeta):
    """Teddy User元类"""
    def __new__(mcs, classname, bases, class_dict):
        # TeddyUser类本身, 忽略
        if classname == 'TeddyUser':
            return type.__new__(mcs, classname, bases, class_dict)

        # 默认非abstract
        if not hasattr(class_dict, 'abstract'):
            class_dict['abstract'] = False

        # 收集tasksets
        tasksets = class_dict['tasks']
        teddy_tasksets: [Type[TeddyTaskSet]] = []
        for taskset in tasksets:
            if not issubclass(taskset, TeddyTaskSet):
                raise TeddyException(f'Invalid teddy taskset: {taskset}')
            if not hasattr(taskset, 'teddy_info'):
                raise TeddyException(f'Not found @teddy_taskset annotation in taskset: {taskset}')

            if taskset in teddy_tasksets:
                teddy_logger.warning(f'Repeatly add taskset: {taskset.__class__.__name__}')

            teddy_tasksets.append(taskset)
            teddy_logger.debug(f'Find taskset: {taskset.__class__.__name__}')

        if not teddy_tasksets:
            raise TeddyException('Please use the <tasks> property to specific one or more taskset(s)')
        class_dict['tasks'] = teddy_tasksets

        # 注入user id生成支持
        class_dict['_user_id_begin'] = int(time.time()) << 32
        def _gen_user_id(the_self):
            user_id = the_self.__class__._user_id_begin + 1
            the_self.__class__._user_id_begin = user_id
            return user_id
        class_dict['_gen_user_id'] = _gen_user_id

        # 改写on_start/on_stop, 以实现taskset的on_init/on_destroy调用
        user_on_start = class_dict['on_start']
        user_on_stop = class_dict['on_stop']

        @functools.wraps(user_on_start)
        def wrapped_user_on_start(user_self):
            for ts in user_self.tasksets:
                ts.on_init()
            user_on_start(user_self)
            teddy_user_mgr._on_user_start(user_self)

        @functools.wraps(user_on_stop)
        def wrapped_user_on_stop(user_self):
            teddy_user_mgr._on_user_stop(user_self)
            user_on_stop(user_self)
            for ts in reversed(user_self.tasksets):
                ts.on_destroy()

        class_dict['on_start'] = wrapped_user_on_start
        class_dict['on_stop'] = wrapped_user_on_stop

        return type.__new__(mcs, classname, bases, class_dict)


class TeddyUser(User, metaclass=TeddyUserMeta):
    """Teddy User封装"""

    """抽象User类"""
    abstract = True

    def __init__(self, environment):
        super().__init__(environment)
        self._user_logic_id = 0
        self._user_id = self._gen_user_id()
        self._taskset_instance = TeddyTopTaskSet(self)

    @property
    def user_id(self):
        """取得user Id"""
        return self._user_id

    @property
    def user_logic_id(self):
        return self._user_logic_id

    @user_logic_id.setter
    def user_logic_id(self, new_user_logic_id):
        if new_user_logic_id == self._user_logic_id:
            return

        old_user_logic_id = self._user_logic_id
        self._user_logic_id = new_user_logic_id
        teddy_user_mgr._on_update_user_logic_id(self, old_user_logic_id)

    @property
    def tasksets(self) -> [TeddyTaskSet]:
        """返回所有Tasksets"""
        return self._taskset_instance.tasksets

    def get_cur_taskset(self) -> Union[TeddyTaskSet, None]:
        """
        获取当前任务集
        :return: 当前任务对象, 如不存在或未启动, 返回None
        """
        return self._taskset_instance.get_cur_taskset()

    def get_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str) -> Union[TeddyTaskSet, None]:
        """
        获取指定任务集
        :param taskset_cls_or_name: (optional) 任务集类或类名
        :return: 任务集对象, 如找不到则返回空
        """
        return self._taskset_instance.get_taskset(taskset_cls_or_name)

    def __str__(self):
        return f'{self.__class__.__name__}[{self._state}, {self._user_id}|{self._user_logic_id}]'
