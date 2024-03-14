from enum import Enum
from typing import TypedDict, Optional, List, Callable


class TeddyCfg:
    """Teddy配置选项"""

    """调试选项"""
    debug = False


TeddyTaskT = Callable[..., None]
"""Teddy Task类型"""


class TeddyMsgType(Enum):
    """Teddy消息类型"""
    Send = 1
    """发送类型Msg"""

    Recv = 2
    """接收类型Msg"""


class TeddyMsgRecord(TypedDict):
    """Teddy消息记录"""
    msg_type: int
    """网络消息类型, 见<TeddyNetMsgType>"""
    msg_id: int
    """消息id/opcode/cmd_id"""
    msg_len: int
    """消息长度"""
    status: int
    """消息状态码"""


class TeddyPairedMsgRecord(TypedDict):
    """Teddy Paired消息记录"""
    send_msg_id: int
    """发送消息Id"""
    send_msg_size: int
    """发送消息大小"""
    recv_msg_id: int
    """接收消息Id"""
    recv_msg_size: int
    """接收消息大小"""
    recv_msg_status: int
    """接收消息status"""
    cost_time: float
    """耗时, 秒为单位"""


class TeddyTaskScheduleMode(Enum):
    """Teddy任务调度模式"""
    Sequential = 1
    """顺序调度"""

    Randomized = 2
    """随机调度"""

    Fixed_Sequential = 3
    """
    定序的顺序调度, 需要提供确定序列
    - 针对TeddyTaskSet, 需要提供fixed_task_list列表
    - 针对TeddyUser, 需要提供fixed_taskset_list列表
    """

    Fixed_Randomized = 4
    """
    定序的随机调度
    - 针对TeddyTaskSet, 需要提供fixed_task_list列表
    - 针对TeddyUser, 需要提供fixed_taskset_list列表
    """

    @classmethod
    def is_fixed_schedule_mode(cls, task_schedule_mode: "TeddyTaskScheduleMode") -> bool:
        """确认给定task schedule mode是否是定序模式"""
        return task_schedule_mode in (cls.Fixed_Sequential, cls.Fixed_Randomized)

    @classmethod
    def is_randomomized_schedule_mode(cls, task_schedule_mode: "TeddyTaskScheduleMode") -> bool:
        """确认给定task schedule mode是否是随机模式"""
        return task_schedule_mode in (cls.Randomized, cls.Fixed_Randomized)


class TeddyTaskSetType(Enum):
    """Teddy任务集类型"""
    Base = 1
    """
    基础任务集
    默认调度策略: TeddyTaskScheduleMode.Sequential
    """

    Func = 2
    """
    功能测试任务集
    默认调度策略: TeddyTaskScheduleMode.Sequential
    """

    Coverage = 3
    """
    覆盖性测试任务集
    默认调度策略: TeddyTaskScheduleMode.Randomized
    """

    UserDefined1 = 4
    """
    用户自定义测试任务集1(交给用户来定义此任务集分类)
    默认调度策略: TeddyTaskScheduleMode.Sequential
    """

    UserDefined2 = 5
    """
    用户自定义测试任务集2(交给用户来定义此任务集分类)
    默认调度策略: TeddyTaskScheduleMode.Sequential
    """

    @classmethod
    def get_default_schedule_mode(cls, taskset_type: "TeddyTaskSetType") -> TeddyTaskScheduleMode:
        """获取指定taskset类型的默认调度模式"""
        if taskset_type == cls.Coverage:
            return TeddyTaskScheduleMode.Randomized
        else:  # Non-Coverage
            return TeddyTaskScheduleMode.Sequential


class TeddyType(Enum):
    """Teddy扩展的元素类型"""
    TaskSet = 1
    """任务集, 指示是一个Teddy任务集"""

    Task = 2
    """任务, 属于任务集"""


class TeddyInfo(TypedDict):
    """描述一个Teddy信息"""
    teddy_type: TeddyType  # Teddy类型, 见TeddyType
    name: str  # 名, 一般为class name or method name
    desc: Optional[str]  # 描述, 通过特定annotation的desc参数指定
    index: int  # 任务在任务集中的下标索引 or 任务集在user中的索引(排序后)
    taskset_type: Optional[TeddyTaskSetType]  # 任务集类型, 只在TaskSet的Teddy类型有效
    order: Optional[int]  # 顺序, 只在Task的Teddy类型有效
    beg_exec_time: Optional[float]  # 开始执行时间, 只在Task的Teddy类型有效
    total_send_bytes: Optional[int]  # 总发送的字节数, 只在Task的Teddy类型有效
    total_recv_bytes: Optional[int]  # 总接收的字节数, 只在Task的Teddy类型有效
    send_msgs: Optional[List[TeddyMsgRecord]]  # 已发送的消息, 只在Task的Teddy类型有效
    recv_msgs: Optional[List[TeddyMsgRecord]]  # 已接收的消息, 只在Task的Teddy类型有效
    paired_msgs: Optional[List[TeddyPairedMsgRecord]]  # 已进行的Paired Messages
    fail: Exception | str | None  # 失败信息, 只在Task的Teddy类型有效
    stop_user_after_fail: Optional[bool]  # 失败有失败信息, 是否在上报后停止此User
