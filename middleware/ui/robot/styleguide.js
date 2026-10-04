import {createTaskChooser} from "/common/task-chooser.js";
const chooser = createTaskChooser({tasks: [{id: "input", title: "입력", panel: document.getElementById("task-input")}, {id: "readback", title: "결과 확인", panel: document.getElementById("task-readback")}]});
document.getElementById("task-demo").append(chooser.element); chooser.setReady();
