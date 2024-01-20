from typing import TypedDict, Optional, List


class TeddyCfg:
    """Teddy配置选项"""

    """调试选项"""
    debug = False


class TeddyMsgType:
    """Teddy消息类型"""
    Send = 1  # 发送类型Msg
    Recv = 2  # 接收类型Msg


class TeddyMsgRecord(TypedDict):
    """Teddy消息记录"""
    msg_type: int  # 网络消息类型, 见<TeddyNetMsgType>
    msg_id: int  # 消息id/opcode/cmd_id
    msg_len: int  # 消息长度
    status: int  # 消息状态码


class TeddyPairedMsgRecord(TypedDict):
    """Teddy Paired消息记录"""
    send_msg_id: int  # 发送消息Id
    send_msg_size: int  # 发送消息大小
    recv_msg_id: int  # 接收消息Id
    recv_msg_size: int  # 接收消息大小
    recv_msg_status: int  # 接收消息status
    cost_time: float  # 耗时, 秒为单位


class TeddyType:
    """Teddy扩展的元素类型"""
    TaskSet = 1  # 任务集, 指示是一个Teddy任务集
    Task = 2  # 任务, 属于任务集


class TeddyInfo(TypedDict):
    """描述一个Teddy信息"""
    teddy_type: int  # Teddy类型, 见TeddyType
    name: str  # 名, 一般为class name or method name
    desc: Optional[str]  # 描述, 通过特定annotation的desc参数指定
    order: Optional[int]  # 顺序, 只在Task的Teddy类型有效
    index: Optional[int]  # 任务在任务集中的下标索引
    beg_exec_time: Optional[float]  # 开始执行时间, 只在Task的Teddy类型有效
    total_send_bytes: Optional[int]  # 总发送的字节数, 只在Task的Teddy类型有效
    total_recv_bytes: Optional[int]  # 总接收的字节数, 只在Task的Teddy类型有效
    send_msgs: Optional[List[TeddyMsgRecord]]  # 已发送的消息, 只在Task的Teddy类型有效
    recv_msgs: Optional[List[TeddyMsgRecord]]  # 已接收的消息, 只在Task的Teddy类型有效
    paired_msgs: Optional[List[TeddyPairedMsgRecord]]  # 已进行的Paired Messages
    fail: Exception | str | None  # 失败信息, 只在Task的Teddy类型有效
    stop_user_after_fail: Optional[bool]  # 失败有失败信息, 是否在上报后停止此User


class TeddyMsgReport(TypedDict):
    msg_type: int  # 消息类型,


class TeddyReport(TypedDict):
    """Teddy报告"""
    task_start_perf_counter: float  # 任务启动时的perf counter


