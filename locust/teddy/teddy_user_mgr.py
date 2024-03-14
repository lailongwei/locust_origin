from typing import List

from locust.teddy import teddy_logger


class TeddyUserMgr:
    """
    Teddy User管理器封装
    """
    def __init__(self):
        self._user_ids: List[int] = []

        self._seq_2_users = {}
        self._user_id_2_users = {}
        self._user_name_2_users = {}
        self._user_logic_id_2_users = {}

    @property
    def user_ids(self) -> List[int]:
        return self._user_ids

    @property
    def seq_2_users(self):
        return self._seq_2_users

    @property
    def user_id_2_users(self):
        return self._user_id_2_users

    @property
    def user_logic_id_2_users(self):
        return self._user_logic_id_2_users

    @property
    def user_name_2_users(self):
        return self._user_name_2_users

    def get_by_user_id(self, user_id: int):
        return self._user_id_2_users.get(user_id)

    def get_by_user_logic_id(self, user_logic_id: int):
        return self._user_logic_id_2_users.get(user_logic_id)

    def get_by_user_name(self, user_name: str):
        return self._user_name_2_users.get(user_name)

    def _on_user_start(self, user):
        self._user_ids.append(user.user_id)
        self._seq_2_users[user.seq] = user
        self._user_id_2_users[user.user_id] = user
        teddy_logger.info(f'Add user: {user}')

    def _on_user_stop(self, user):
        teddy_logger.info(f'Remove user: {user}')
        self._user_ids.remove(user.user_id)
        del self._seq_2_users[user.seq]
        del self._user_id_2_users[user.user_id]
        self.__remove_user_from_logic_id_dict(user.user_logic_id, user.user_id)

    def _on_update_user_name(self, user, old_user_name):
        teddy_logger.debug(f'Update user name, user: {user}, '
                           f'old_user_name: {old_user_name}')

        self.__remove_user_from_user_name_dict(old_user_name, user.user_id)
        if user.user_name:
            user_name_users = self._user_name_2_users.get(user.user_name)
            if user_name_users is None:
                user_name_users = {}
                self._user_name_2_users[user.user_name] = user_name_users
            user_name_users[user.user_name] = user

    def _on_update_user_logic_id(self, user, old_user_logic_id):
        teddy_logger.debug(f'Update user logic id, user: {user}, '
                           f'old_user_logic_id: {old_user_logic_id}')

        self.__remove_user_from_logic_id_dict(old_user_logic_id, user.user_id)
        if user.user_logic_id != 0:
            logic_id_users = self._user_logic_id_2_users.get(user.user_logic_id)
            if logic_id_users is None:
                logic_id_users = {}
                self._user_logic_id_2_users[user.user_logic_id] = logic_id_users
            logic_id_users[user.user_id] = user

    def __remove_user_from_user_name_dict(self, user_name, user_id):
        if (not user_name or
                user_name not in self._user_name_2_users):
            return

        user_name_users = self._user_name_2_users[user_name]
        if user_id not in user_name_users:
            return

        del user_name_users[user_id]
        if not user_name_users:
            del self._user_name_2_users[user_name]

    def __remove_user_from_logic_id_dict(self, user_logic_id, user_id):
        if (user_logic_id == 0 or
                user_logic_id not in self._user_logic_id_2_users):
            return

        logic_id_users = self._user_logic_id_2_users[user_logic_id]
        if user_id not in logic_id_users:
            return

        del logic_id_users[user_id]
        if not logic_id_users:
            del self._user_logic_id_2_users[user_logic_id]


"""Teddy user管理器唯一实例"""
teddy_user_mgr = TeddyUserMgr()
