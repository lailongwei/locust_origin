from typing import TypedDict, Optional


class TeddyCfg:
    """Teddy配置选项"""

    """调试选项"""
    debug = False


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


class TeddyNetMsgType:
    """Teddy网络消息类型"""
    Send = 1  # 发送类型Msg
    Recv = 2  # 接收类型Msg
    SendAndRecv = 3  # 发送且等待接收类型Msg


class TeddyNetMsgRecord(TypedDict):
    """Teddy网络消息记录"""
    net_msg_type: int  # 网络消息类型, 见<TeddyNetMsgType>
    send_msg_bytes: Optional[int]  # 发送消息bytes, 对Send/SendAndRecv类型的msg type有效
    recv_msg_bytes: Optional[int]  # 接收消息bytes, 对Recv/SendAndRecv类型的msg type有效
    send_perf_counter: Optional[float]  # 发送时的perf counter, 对Send/SendAndRecv类型的msg type有效
    recv_perf_counter: Optional[float]  # 接收时的perf counter, 对Recv/SendAndRecv类型的msg type有效
    recv_status_code: int


class TeddyMsgReport(TypedDict):
    msg_type: int  # 消息类型,


class TeddyReport(TypedDict):
    """Teddy报告"""
    task_start_perf_counter: float  # 任务启动时的perf counter


