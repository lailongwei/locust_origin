import functools
import inspect
import logging
import random
import time
from typing import Type, List

from ..user.users import UserMeta, User

from . import teddy_logger, TeddySession
from .teddy_def import TeddyTaskSetType, TeddyTaskScheduleMode
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
        tasksets = teddy_tasksets

        # 按taskset type正序排序
        tasksets.sort(key=lambda ts: ts.teddy_info['taskset_type'].value)
        for taskset_index in range(len(tasksets)):
            tasksets[taskset_index].teddy_info['index'] = taskset_index

        # 更新user.tasks
        class_dict['tasks'] = teddy_tasksets

        # 分taskset type存储
        class_dict['taskset_type_2_tasks'] = {}
        for taskset_type in TeddyTaskSetType.__members__.values():
            class_dict['taskset_type_2_tasks'][taskset_type] = \
                [taskset for taskset in tasksets if taskset.teddy_info['taskset_type'] == taskset_type]

        # 确定任务taskset调度模式
        taskset_schedule_mode = class_dict.setdefault('taskset_schedule_mode', {})
        if not isinstance(taskset_schedule_mode, dict):
            raise TeddyException(f'User <taskset_schedule_mode> must be a dict, user: {classname}')

        for taskset_type in TeddyTaskSetType.__members__.values():
            if taskset_type not in class_dict['taskset_schedule_mode']:
                class_dict['taskset_schedule_mode'][taskset_type] = \
                    TeddyTaskSetType.get_default_schedule_mode(taskset_type)
            elif class_dict['taskset_schedule_mode'][taskset_type] not in TeddyTaskScheduleMode:
                raise TeddyException(f'Invalid taskset schedule mode, '
                                     f'user: {classname}, '
                                     f'taskset_type: {taskset_type}, '
                                     f'schedule_mode: {class_dict["taskset_schedule_mode"][taskset_type]}')

        # 标准化定序调度模式下的定序列表: fixed_taskset_list
        for taskset_type in TeddyTaskSetType.__members__.values():
            # 非Fixed模式, continue
            taskset_schedule_mode: TeddyTaskScheduleMode = class_dict['taskset_schedule_mode'][taskset_type]
            if not TeddyTaskScheduleMode.is_fixed_schedule_mode(taskset_schedule_mode):
                continue

            # 得到fixed_taskset_list
            fixed_taskset_list: List[Type[TeddyTaskSet]] = \
                class_dict.setdefault('fixed_taskset_list', {}).setdefault(taskset_type, [])
            if not isinstance(fixed_taskset_list, list):
                fixed_taskset_list = list(fixed_taskset_list)
                class_dict['fixed_taskset_list'][taskset_type] = fixed_taskset_list

            # 标准化fixed_taskset_list
            type_tasksets: List[Type[TeddyTaskSet]] = class_dict[taskset_type.name.lower() + '_tasks']
            if not fixed_taskset_list:  # 空: 自动填充此taskset类型的tasksets
                fixed_taskset_list.extend(type_tasksets)
            else:  # 非空: 执行标准化
                for taskset_index in range(len(fixed_taskset_list)):
                    ts = fixed_taskset_list[taskset_index]
                    if isinstance(ts, str):
                        for taskset in type_tasksets:
                            if taskset.__name__ == ts:
                                fixed_taskset_list[taskset_index] = taskset
                                break
                    elif (not inspect.isclass(ts) or
                            not issubclass(ts, TeddyTaskSet)):
                        raise TeddyException(f'Invalid <fixed_taskset_list> config item, '
                                             f'user: {classname}, '
                                             f'taskset_type: {taskset_type}, '
                                             f'config_item: {ts}')

            # 如 标准化后还为空, raise exception
            if not fixed_taskset_list:
                raise TeddyException(f'<fixed_taskset_list> is empty, user: {classname},'
                                     f'taskset_type: {taskset_type}')

        # 如未设置独占调度, 设置默认值(默认: True)
        if 'exclusive_schedule' not in class_dict:
            class_dict['exclusive_schedule'] = True

        # 注入taskset.cfg配置项
        user_cfg = class_dict.get('cfg')
        if (user_cfg is not None and
                'tasksets' in user_cfg):
            taskset_cfgs = user_cfg['tasksets']
            for taskset in tasksets:
                if taskset.__name__ in taskset_cfgs:
                    setattr(taskset, 'cfg', taskset_cfgs[taskset.__name__])
                else:
                    setattr(taskset, 'cfg', None)
        else:
            for taskset in tasksets:
                setattr(taskset, 'cfg', None)

        # 注入user id生成支持
        # reserved | timestamp |  seq  |
        #   22bit  |   32bit   | 10bit |
        class_dict['_user_id_seq'] = 0

        def _gen_user_id(the_self):
            user_cls = the_self.__class__
            user_cls._user_id_seq += 1
            user_id = (int(time.time()) << 10) | user_cls._user_id_seq
            return user_id
        class_dict['_gen_user_id'] = _gen_user_id

        # 改写on_start/on_stop, 以实现taskset的on_init/on_destroy调用
        user_on_start = class_dict.get('on_start')
        if user_on_start is None:
            def _dft_user_on_start(user_self):
                pass
            user_on_start = _dft_user_on_start

        user_on_stop = class_dict.get('on_stop')
        if user_on_stop is None:
            def _dft_user_on_stop(user_self):
                pass
            user_on_stop = _dft_user_on_stop

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

            if user_self.session:
                user_self.session.destroy()
                user_self.session = None

        class_dict['on_start'] = wrapped_user_on_start
        class_dict['on_stop'] = wrapped_user_on_stop

        return type.__new__(mcs, classname, bases, class_dict)


class TeddyUser(User, metaclass=TeddyUserMeta):
    """Teddy User封装"""

    """抽象User类"""
    abstract = True

    # region __init__
    def __init__(self, environment):
        super().__init__(environment)
        self._user_id: int = self._gen_user_id()
        self._user_name: str = ''
        self._user_logic_id = 0
        self._session: TeddySession | None = None
        self._taskset_instance: TeddyTopTaskSet = TeddyTopTaskSet(self)
    # endregion

    # region properties
    @property
    def user_id(self):
        """取得user Id"""
        return self._user_id

    @property
    def user_name(self) -> str:
        """获取用户名(业务层使用, 不需要保证唯一, 空时将不建立索引)"""
        return self._user_name

    @user_name.setter
    def user_name(self, new_user_name: str) -> None:
        """设置用户名"""
        if new_user_name == self._user_name:
            return

        old_user_name = self._user_name
        self._user_name = new_user_name
        teddy_user_mgr._on_update_user_name(self, old_user_name)

    @property
    def user_logic_id(self) -> int:
        """取得user logic id(业务层使用, 不需要保证唯一, 空时将不建立索引)"""
        return self._user_logic_id

    @user_logic_id.setter
    def user_logic_id(self, new_user_logic_id: int) -> None:
        """更新logic id"""
        if new_user_logic_id == self._user_logic_id:
            return

        old_user_logic_id = self._user_logic_id
        self._user_logic_id = new_user_logic_id
        teddy_user_mgr._on_update_user_logic_id(self, old_user_logic_id)

    @property
    def session(self) -> TeddySession:
        """取得会话对象"""
        return self._session

    @session.setter
    def session(self, session: TeddySession):
        """设置会话对象"""
        self._session = session

    @property
    def tasksets(self) -> [TeddyTaskSet]:
        """返回所有Tasksets"""
        return self._taskset_instance.tasksets

    @property
    def user_state(self) -> int:
        """用户状态, -1表示无状态, 要求业务层重写"""
        return -1
    # endregion

    # region task/taskset操作
    def get_cur_taskset(self) -> TeddyTaskSet | None:
        """
        获取当前任务集
        :return: 当前任务对象, 如不存在或未启动, 返回None
        """
        return self._taskset_instance.get_cur_taskset()

    def get_taskset(self, taskset_cls_or_name: Type[TeddyTaskSet] | str) -> TeddyTaskSet | None:
        """
        获取指定任务集
        :param taskset_cls_or_name: (optional) 任务集类或类名
        :return: 任务集对象, 如找不到则返回空
        """
        return self._taskset_instance.get_taskset(taskset_cls_or_name)
    # endregion

    # region user/taskset事件方法调用支持
    def invoke_event_method(self,
                            method_name: str,
                            /, *,
                            reverse: bool = False,
                            skip_user: bool = False,
                            require_user_state: int = -1,
                            **method_params) -> bool:
        """
        调用事件方法, 要求以on_开头, 正向: tasksets->user, 反向: user->reversed tasksets
        :param method_name: 方法名
        :param reverse: (optional) 是否反向调用, 默认False
        :param skip_user: (optional) 是否跳过User方法调用, 即只调用component方法, 默认False
        :param require_user_state: (optional) 要求的user state, 默认-1, 即: 无要求
        :param method_params: 方法参数
        :returns: 是否调用成功
        """
        # 用户状态校验
        if (require_user_state >= 0 and
                self.user_state < require_user_state):
            return False

        # 方法名校验
        if not method_name.startswith('on_'):
            raise TeddyException('User event method must be starts with <on_>')

        # 调用
        user_method = getattr(self, method_name) if (not skip_user and hasattr(self, method_name)) else None
        if reverse and user_method is not None:
            user_method(**method_params)

        for taskset in reversed(self.tasksets) if reverse else self.tasksets:
            method = getattr(taskset, method_name) if hasattr(taskset, method_name) else None
            if method:
                method(**method_params)

        if not reverse and user_method is not None:
            user_method(**method_params)
    # endregion

    # region 日志输出支持
    def log(self, log_level: int, msg: object):
        """输出日志"""
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
        # usr[state|id:xx|lid:xx|sid:xx]
        str_repr = (f'{self.__class__.__name__}'
                    f'[{self._state}'
                    f'|id:{self._user_id}'
                    f'|lid:{self._user_logic_id}'
                    f'|sid:{self.session.session_id if self.session is not None else -1}]')
        return str_repr
    # endregion
