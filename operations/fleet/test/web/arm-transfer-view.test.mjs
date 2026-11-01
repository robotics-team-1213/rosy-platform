import test from "node:test";
import assert from "node:assert/strict";
const {register} = await import("node:module");
register("./resolve-console-assets.mjs", import.meta.url);
const {armAdmissionReason} = await import("../../../../applications/fleet/web/work/arm-transfer-view.js");
const job = {status: "PROPOSED", proposal_principal_id: "proposer"};
const control = {dispatch_enabled: true, generation: 3};
test("neutral ARM approval requires independent identity, current control, and an unapproved proposal", () => {
  assert.equal(armAdmissionReason(job, control, "independent"), "");
  for (const [row, fence, actor, role] of [[null, control, "independent"], [job, control, "proposer"],
    [job, control, ""], [job, null, "independent"], [job, {...control, generation: -1}, "independent"],
    [job, {...control, dispatch_enabled: false}, "independent"], [{...job, status: "HOLD"}, control, "independent"],
    [job, control, "independent", "read only"]]) assert.ok(armAdmissionReason(row, fence, actor, role));
});
