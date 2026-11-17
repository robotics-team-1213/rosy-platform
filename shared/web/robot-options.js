/**
 * G5 robot picker helper: robot profiles -> the [{value, label}] a native select (or createChoiceGroup) takes, so every
 * "pick a robot" field names a robot the same way as the row (robot-row.js). Pure (robot-profile.js and value-text.js
 * have no DOM).
 *
 *   robotOptions(profiles) -> [{value: id, label}]
 *     order  arms first, then mobile robots (groupRobots), input order inside a group
 *     label  "이름 · 종류" ("OMX-AI A · 로봇암"); a robot without a name reads "rosy_40 · 이동로봇", never "undefined"
 *     empty  [] (the screen shows ui-empty; a select never offers a robot that is not there)
 */
import {groupRobots} from "./robot-profile.js";
import {valueText} from "./value-text.js";

export function robotOptions(profiles) {
  return groupRobots(profiles).flatMap(group => group.rows.map(profile => ({
    value: profile.id,
    label: `${profile.name || valueText(null).text} · ${profile.kindLabel}`,
  })));
}
