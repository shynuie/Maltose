from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def test_offline_csp_and_no_executable_agent_surfaces():
    html=(ROOT/'packages/renderer/dist/index.html').read_text()
    assert "connect-src 'none'" in html
    assert 'https://' not in html
    source=(ROOT/'apps/macos/MaltoseApp/WebSurface.swift').read_text()
    assert 'evaluateJavaScript' not in source
    assert 'isMainFrame' in source and 'isFileURL' in source
    assert 'WKNavigationActionPolicy' in source
    transport=(ROOT/'native/Transport/LoopbackServer.swift').read_text()
    assert 'requiredLocalEndpoint' in transport and '"127.0.0.1"' in transport
    assert '"origin"' in transport
