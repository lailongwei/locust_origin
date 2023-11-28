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
        self._session_state: str = TeddySessionState.Disconnected

    @property
    def user(self):
        """获得所属User对象"""
        return self._user

    @property
    def session_id(self):
        """传话Id"""
        return self._session_id

    @property
    def session_state(self) -> str:
        """传话状态"""
        return self._session_state

    @property
    def connected(self) -> bool:
        """指示是否已连接"""
        return self._session_state == TeddySessionState.Connected

    def connect(self, **kwargs) -> None:
        """连接"""
        raise NotImplemented()

    def disconnect(self) -> None:
        """断开连接"""
        raise NotImplemented()

    def send(self, data: bytes) -> None:
        """
        发送数据
        :param data: 要发送的数据
        """
        raise NotImplemented()

    def recv(self, recv_len: int = -1) -> bytes:
        """
        接收数据
        :param recv_len: (optional) 要接收的数据数量, 如不指定将尽可能接收
        :return: 接收到的数据
        """
        raise NotImplemented()

    def __str__(self):
        return f'{self.__class__.__name__}[{self._session_id}, {self._session_state}]'
