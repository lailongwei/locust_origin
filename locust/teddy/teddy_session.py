from typing import Any


class TeddySessionState:
    """Teddy会话状态"""
    Disconnected = 'Disconnected'
    Connecting = 'Connecting'
    Connected = 'Connected'
    Reconnecting = 'Reconnecting'


class TeddySession:
    """Teddy会话对象"""
    _max_session_id = 0

    def __init__(self, user):
        self._user = user

        self.__class__._max_session_id += 1
        self._session_id = self.__class__._max_session_id

    @property
    def user(self) -> "TeddyUser":
        """获得所属User对象"""
        return self._user

    @property
    def session_id(self) -> int:
        """传话Id"""
        return self._session_id

    @property
    def session_state(self) -> str:
        """传话状态"""
        raise NotImplemented()

    @property
    def connected(self) -> bool:
        """指示是否已连接"""
        return self.session_state == TeddySessionState.Connected

    def init(self, *args, **kwargs) -> None:
        """初始化"""
        raise NotImplemented()

    def destroy(self) -> None:
        """销毁"""
        raise NotImplemented()

    def connect(self, *args, **kwargs) -> None:
        """连接"""
        raise NotImplemented()

    def disconnect(self) -> None:
        """断开连接"""
        raise NotImplemented()

    def send(self, **kwargs) -> Any:
        """
        发送数据
        :param kwargs: 发送参数(由子类重写并规定)
        :returns: 任意对象, TeddySession不作约束
        """
        raise NotImplemented()

    def recv(self, **kwargs) -> bytes:
        """
        接收数据
        :param kwargs: 接收参数(由子类重写并规定)
        :returns: 接收到的数据
        """
        raise NotImplemented()

    def send_and_recv(self, **kwargs) -> Any:
        """
        发送并接收数据
        :param kwargs: 调用参数(由子类重写并规定)
        :returns: 任意对象, TeddySession不作约束
        """
        raise NotImplemented()

    def __str__(self):
        return f'{self.__class__.__name__}[{self._session_id}, {self.session_state}]'
