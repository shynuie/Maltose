import threading
import unittest
from unittest.mock import patch
from maltose.agent.agent import VoiceAgent
from maltose.voice.listening import ListeningEvent, VADSettings, microphone_events


class NativeAudioStateTests(unittest.TestCase):
    def test_audio_active_is_reported_after_open_and_inactive_after_stream_close(self):
        events = []
        class Stream:
            def __enter__(self): events.append('opened'); return self
            def __exit__(self, *_): events.append('closed')
        stop = threading.Event(); stop.set()
        with patch('sounddevice.RawInputStream', return_value=Stream()):
            list(microphone_events(VADSettings(), stop_event=stop, on_audio_state=lambda active: events.append('active' if active else 'inactive')))
        self.assertEqual(events, ['opened', 'active', 'closed', 'inactive'])

    def test_failed_stream_open_does_not_claim_the_microphone_is_active(self):
        events = []
        class Stream:
            def __enter__(self): raise RuntimeError('device unavailable')
            def __exit__(self, *_): pass
        with patch('sounddevice.RawInputStream', return_value=Stream()), self.assertRaisesRegex(RuntimeError, 'device unavailable'):
            list(microphone_events(VADSettings(), on_audio_state=events.append))
        self.assertEqual(events, [])
        calls = []
        def invalid_factory(settings, device, timeout, wake, delay, buffer, stop_event=None, *, on_audio_state=None):
            calls.append(True)
            raise TypeError('listener initialization failed')
        with self.assertRaisesRegex(TypeError, 'listener initialization failed'):
            VoiceAgent(listener_factory=invalid_factory)._create_stream_listener(threading.Event())
        self.assertEqual(calls, [True], 'An initialization failure must not retry opening another microphone')

    def test_existing_listener_adapter_tracks_overlapping_stream_lifetimes(self):
        def factory(settings, device, timeout, wake, delay, buffer, stop_event=None, *, on_audio_state=None):
            on_audio_state(True)
            try: yield ListeningEvent(kind='standby_timeout')
            finally: on_audio_state(False)
        agent = VoiceAgent(listener_factory=factory)
        first = agent._invoke_listener(threading.Event(), False)
        second = agent._create_stream_listener(threading.Event())
        next(first); next(second)
        self.assertTrue(agent.audio_input_active)
        first.close()
        self.assertTrue(agent.audio_input_active, 'Closing one stream must not hide another still-active stream')
        second.close()
        self.assertFalse(agent.audio_input_active)
