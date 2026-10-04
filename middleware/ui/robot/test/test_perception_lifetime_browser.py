"""Perception configuration replies cannot outlive their mounted panel."""

import pytest

from test_panel_copy_evidence_browser import panel, pytestmark  # noqa: F401


@pytest.mark.parametrize("held_method", ["PUT", "GET"])
def test_perception_unmount_aborts_without_late_readback_or_dom(panel, held_method):
    page = panel("console/line-follow.js", role="administrator")
    page.evaluate("""method => {
      __callbacks['/api/v1/line-follow'].onData({mode:'OFF'});
      __callbacks['/api/v1/robot/state'].onData({mode:'IDLE',velocity:{linear:0,angular:0}});
      __callbacks['/api/v1/line-follow/perception'].onData({paint_source:'denoise'});
      window.requests=[]; window.requestSignals=[];
      window.__api=(path, options={})=>{
        const verb=options.method || 'GET';
        requests.push({path, method:verb, body:options.body || null});
        requestSignals.push(options.signal);
        if(verb===method) return new Promise(resolve=>window.releasePerception=()=>resolve(
          verb==='PUT'?{applied:true}:{paint_source:'learned',applied_paint_source:'learned',applied_source_age_s:0.1}));
        return Promise.resolve({applied:true});
      };
    }""", held_method)
    page.select_option("select[aria-label='차선 인식 방식']", "learned")
    page.get_by_role("button", name="인식 적용", exact=True).click()
    page.wait_for_function("() => typeof releasePerception === 'function'")
    requests = page.evaluate("requests")
    assert requests == [{"path": "/api/v1/line-follow/perception", "method": "PUT",
                         "body": '{"paint_source":"learned"}'}] + (
        [{"path": "/api/v1/line-follow/perception", "method": "GET", "body": None}]
        if held_method == "GET" else [])
    assert page.evaluate("requestSignals.every(signal=>signal && !signal.aborted)")
    page.evaluate("""() => {
      __unmount.unmount();
      window.oldRoot=document.getElementById('root');
      window.oldDOM=oldRoot.innerHTML; window.lateMutations=[];
      new MutationObserver(records=>lateMutations.push(...records)).observe(oldRoot,
        {subtree:true,childList:true,attributes:true,characterData:true});
    }""")
    assert page.evaluate("requestSignals.every(signal=>signal.aborted)")
    page.evaluate("""async () => {
      releasePerception();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }""")
    assert page.evaluate("requests") == requests
    assert page.evaluate("oldRoot.isConnected && oldRoot.innerHTML===oldDOM")
    assert page.evaluate("lateMutations.length") == 0
