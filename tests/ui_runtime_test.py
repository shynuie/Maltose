import unittest

from maltose_runtime.tools import show_surface
from maltose_runtime.wire import MUPFailure


class FakeWire:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def request(self, name, payload=None):
        self.calls.append((name, payload))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class ShowSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            'surface_id': 'agent-demo',
            'title': 'Demo',
            'document': {'root': {'node_id': 'root', 'type': 'text', 'props': {'text': 'Hello'}}},
        }

    def test_unknown_surface_is_created_after_host_forbidden_response(self):
        wire = FakeWire([
            MUPFailure({'code': 'forbidden', 'message': 'Surface unavailable'}),
            {'surface_id': 'agent-demo', 'revision': 1},
        ])

        result = show_surface(wire, self.payload)

        self.assertEqual(result['revision'], 1)
        self.assertEqual([call[0] for call in wire.calls], ['surface.get', 'surface.create'])

    def test_existing_owned_surface_is_rendered_with_current_revision(self):
        wire = FakeWire([
            {'surface_id': 'agent-demo', 'revision': 7},
            {'surface_id': 'agent-demo', 'revision': 8},
        ])

        show_surface(wire, self.payload)

        self.assertEqual(wire.calls[1][0], 'ui.render')
        self.assertEqual(wire.calls[1][1]['expected_revision'], 7)
        self.assertEqual(wire.calls[1][1]['document'], self.payload['document'])

    def test_foreign_surface_collision_is_not_overwritten(self):
        collision = MUPFailure({'code': 'unavailable', 'message': 'Surface ID unavailable'})
        wire = FakeWire([
            MUPFailure({'code': 'forbidden', 'message': 'Surface unavailable'}),
            collision,
        ])

        with self.assertRaisesRegex(MUPFailure, 'Surface ID unavailable'):
            show_surface(wire, self.payload)

        self.assertEqual([call[0] for call in wire.calls], ['surface.get', 'surface.create'])


if __name__ == '__main__':
    unittest.main()
