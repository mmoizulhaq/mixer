import unittest
import threading
import time
from typing import Optional, Any, Mapping

from mixer.broadcaster.apps.server import Server
from mixer.broadcaster.client import Client
from mixer.broadcaster.client import make_connected_socket
from mixer.broadcaster.socket import Socket
import mixer.broadcaster.common as common

from tests.process import ServerProcess


class Delegate:
    def __init__(self):
        self.clear()

    def clear(self):
        self.clients = None
        self.name_room = None

    def update_rooms_attributes(self, data):
        return None

    def update_clients_attributes(self, data):
        return None


def network_consumer(client, delegate):
    received_commands = client.fetch_commands()

    if received_commands is None:
        return

    for command in received_commands:
        if command.type == common.MessageType.LIST_ROOMS:
            delegate.update_rooms_attributes(command.data)
        elif command.type == common.MessageType.LIST_CLIENTS:
            clients_attributes, _ = common.decode_json(command.data, 0)
            delegate.update_clients_attributes(clients_attributes)


@unittest.skip("")
class TestServer(unittest.TestCase):
    def setUp(self):
        self._delegate = Delegate()
        self._server = Server()
        server_thread = threading.Thread(None, self._server.run)
        server_thread.start()

    def tearDown(self):
        self._server.shutdown()
        self.delay()

    def delay(self):
        time.sleep(0.2)

    def test_connect(self):
        delay = self.delay
        server = self._server

        client1 = Client()
        delay()
        self.assertTrue(client1.is_connected())
        self.assertEqual(server.client_count(), (0, 1))

        client1.disconnect()
        delay()
        self.assertFalse(client1.is_connected())
        self.assertEqual(server.client_count(), (0, 0))

        #
        client2 = Client()
        delay()
        self.assertTrue(client2.is_connected())
        self.assertEqual(server.client_count(), (0, 1))

        client3 = Client()
        delay()
        self.assertTrue(client3.is_connected())
        self.assertEqual(server.client_count(), (0, 2))

        client2.disconnect()
        delay()
        self.assertFalse(client2.is_connected())
        self.assertTrue(client3.is_connected())
        self.assertEqual(server.client_count(), (0, 1))

        client2.disconnect()
        delay()
        self.assertFalse(client2.is_connected())
        self.assertTrue(client3.is_connected())
        self.assertEqual(server.client_count(), (0, 1))

        client3.disconnect()
        delay()
        self.assertFalse(client3.is_connected())
        self.assertEqual(server.client_count(), (0, 0))

    def test_join_one_room_one_client(self):
        delay = self.delay
        server = self._server

        c0_name = "c0_name"
        c0_room = "c0_room"

        d0 = Delegate()
        c0 = Client()
        delay()
        self.assertEqual(server.client_count(), (0, 1))

        c0.set_client_attributes({common.ClientAttributes.USERNAME: c0_name})
        c0.join_room(c0_room)
        delay()
        network_consumer(c0, self._delegate)
        expected = (c0_name, c0_room)
        self.assertEqual(server.client_count(), (1, 0))
        self.assertEqual(len(d0.name_room), 1)
        self.assertIn(expected, d0.name_room)

    def test_join_one_room_two_clients(self):
        delay = self.delay
        server = self._server

        c0_name = "c0_name"
        c0_room = "c0_room"

        c1_name = "c1_name"
        c1_room = c0_room

        d0 = Delegate()
        c0 = Client()
        c0.join_room(c0_room)
        c0.set_client_attributes({common.ClientAttributes.USERNAME: c0_name})

        d1 = Delegate()
        c1 = Client()
        c1.join_room(c1_room)
        c1.set_client_attributes({common.ClientAttributes.USERNAME: c1_name})

        delay()

        network_consumer(c0, self._delegate)
        network_consumer(c1, self._delegate)
        expected = [(c0_name, c0_room), (c1_name, c1_room)]
        self.assertEqual(server.client_count(), (2, 0))
        self.assertEqual(len(d0.name_room), 2)
        self.assertEqual(len(d1.name_room), 2)
        self.assertCountEqual(d0.name_room, expected)
        self.assertCountEqual(d1.name_room, expected)

    def test_join_one_room_two_clients_leave(self):
        delay = self.delay
        server = self._server

        c0_name = "c0_name"
        c0_room = "c0_room"

        c1_name = "c1_name"
        c1_room = c0_room

        d0 = Delegate()
        c0 = Client()
        c0.join_room(c0_room)
        c0.set_client_attributes({common.ClientAttributes.USERNAME: c0_name})

        d1 = Delegate()
        c1 = Client()
        c1.join_room(c1_room)
        c1.set_client_attributes({common.ClientAttributes.USERNAME: c1_name})

        c1.leave_room(c1_room)

        delay()
        network_consumer(c0, self._delegate)
        network_consumer(c1, self._delegate)
        expected = [(c0_name, c0_room)]
        self.assertEqual(server.client_count(), (1, 1))
        self.assertEqual(len(d0.name_room), 1)
        self.assertCountEqual(d0.name_room, expected)
        self.assertListEqual(d0.name_room, d1.name_room)


class SimpleClient:
    socket: Optional[Socket] = None
    host: str
    port: int

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def __del__(self):
        if self.is_connected():
            self.disconnect()

    def __enter__(self):
        if not self.is_connected():
            self.connect()
        return self

    def __exit__(self, *args):
        if self.is_connected():
            self.disconnect()

    def connect(self) -> None:
        if self.is_connected():
            raise RuntimeError("Client.connect : already connected")
        self.socket = make_connected_socket(self.host, self.port)

    def disconnect(self) -> None:
        if self.socket:
            self.socket.shutdown_and_close()
            self.socket = None

    def is_connected(self) -> bool:
        return self.socket is not None

    def send_command(self, *args) -> None:
        common.write_message(self.socket, common.Command(*args))

    def wait_incoming_command(self, timeout: float) -> Optional[common.Command]:
        assert self.socket
        return common.read_message(self.socket, timeout=timeout)


DEFAULT_PROTOCOL_TIMEOUT: float = 10


class TestProtocol(unittest.TestCase):
    def setUp(self):
        self._server_process = ServerProcess(test_own_connection=False)
        self._server_process.start(["--log-level", "DEBUG", "--log-server-updates"])

    def tearDown(self):
        self._server_process.kill()

    def wait_incoming_command(self, client: SimpleClient, message_type: common.MessageType) -> common.Command:
        command = client.wait_incoming_command(DEFAULT_PROTOCOL_TIMEOUT)
        self.assertIsNotNone(command)
        assert command is not None  # Avoid static type warnings on lines below
        self.assertEqual(command.type, message_type)
        return command

    def wait_single_client_update(self, client: SimpleClient) -> Mapping[str, Any]:
        command = self.wait_incoming_command(client, common.MessageType.CLIENT_UPDATE)
        client_update, _ = common.decode_json(command.data, 0)
        self.assertEqual(len(client_update), 1)
        update = client_update[next(iter(client_update))]
        return update

    def wait_single_room_update(self, client: SimpleClient) -> Mapping[str, Any]:
        command = self.wait_incoming_command(client, common.MessageType.ROOM_UPDATE)
        room_update, _ = common.decode_json(command.data, 0)
        self.assertEqual(len(room_update), 1)
        update = room_update[next(iter(room_update))]
        return update

    def assert_all_client_attributes(self, update: Mapping[str, Any]):
        self.assertIn(common.ClientAttributes.ID, update)
        self.assertIn(common.ClientAttributes.IP, update)
        self.assertIn(common.ClientAttributes.PORT, update)
        self.assertIn(common.ClientAttributes.ROOM, update)

    def assert_all_room_attributes(self, update: Mapping[str, Any]):
        self.assertIn(common.RoomAttributes.NAME, update)
        self.assertIn(common.RoomAttributes.KEEP_OPEN, update)
        self.assertIn(common.RoomAttributes.COMMAND_COUNT, update)
        self.assertIn(common.RoomAttributes.BYTE_SIZE, update)
        self.assertIn(common.RoomAttributes.JOINABLE, update)

    def test_join_room_new_room_is_created(self):
        # Test /doc/protocol.md#join_room when room does not exist
        server_process = self._server_process
        with SimpleClient(server_process.host, server_process.port) as client:
            client_update = self.wait_single_client_update(client)
            self.assert_all_client_attributes(client_update)
            self.assertIsNone(client_update[common.ClientAttributes.ROOM])

            room_name = "new_test_room"
            client.send_command(common.MessageType.JOIN_ROOM, room_name.encode("utf8"))

            command = self.wait_incoming_command(client, common.MessageType.JOIN_ROOM)
            self.assertEqual(command.data.decode(), room_name)

            command = self.wait_incoming_command(client, common.MessageType.CONTENT)

            room_update = self.wait_single_room_update(client)
            self.assert_all_room_attributes(room_update)
            self.assertEqual(room_update[common.RoomAttributes.NAME], room_name)
            self.assertEqual(room_update[common.RoomAttributes.KEEP_OPEN], False)
            self.assertEqual(room_update[common.RoomAttributes.COMMAND_COUNT], 0)
            self.assertEqual(room_update[common.RoomAttributes.BYTE_SIZE], 0)
            self.assertEqual(room_update[common.RoomAttributes.JOINABLE], False)

            client_update = self.wait_single_client_update(client)
            self.assertEqual(len(client_update), 1)
            self.assertEqual(client_update[common.ClientAttributes.ROOM], room_name)

            client.send_command(common.MessageType.CONTENT)
            room_update = self.wait_single_room_update(client)
            self.assertEqual(len(room_update), 1)
            self.assertEqual(room_update[common.RoomAttributes.JOINABLE], True)


class TestClient(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_client_is_disconnected_when_server_process_is_killed(self):
        server_process = ServerProcess()
        server_process.start()

        with Client(server_process.host, server_process.port) as client:
            self.assertTrue(client.is_connected())
            client.fetch_commands()

            server_process.kill()

            self.assertRaises(common.ClientDisconnectedException, client.fetch_commands)

            self.assertTrue(not client.is_connected())


if __name__ == "__main__":
    unittest.main()
