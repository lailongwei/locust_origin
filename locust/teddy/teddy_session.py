class TeddySessionState:
    """Teddy会话状态"""
    Disconnected = 0
    Connecting = 1
    Connected = 2
    Reconnecting = 3

    @classmethod
    def get_state_desc(cls, session_state: int) -> str:
        """
        取得传话状态描述
        :param session_state: 会话状态
        :return: 会话状态描述
        """
        if session_state == cls.Disconnected:
            return 'Disconnected'
        elif session_state == cls.Connecting:
            return 'Connecting'
        elif session_state == cls.Connected:
            return 'Connected'
        elif session_state == cls.Reconnecting:
            return 'Reconnecting'
        else:
            return f'UknSessionState{session_state}'


class TeddySession:
    """Teddy会话对象"""
    def __init__(self):
        self._session_id: int = 0
        self._session_state: int = TeddySessionState.Disconnected

    @property
    def session_id(self):
        """传话Id"""
        return self._session_id

    @property
    def session_state(self) -> int:
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
        return (f'{self.__class__.__name__}[f{self._session_id}, '
                f'{TeddySessionState.get_state_desc(self._session_state)}]')
