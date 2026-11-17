// F8: 지도가 없을 때(data-map-state=unavailable) 표시 도구는 숨기지 않고 사유와 함께 잠근다(choice-group의 reason).
export const MAP_TOOLS_LOCK = "지도를 받을 수 없어 쓸 수 없습니다 · 지도가 표시되면 켜지며, 없으면 지도 설정에서 현장 지도를 등록하세요";
export const lockedItems = (items, unavailable) =>
  unavailable ? items.map(item => ({...item, disabled: true, reason: MAP_TOOLS_LOCK})) : items;
export function lockWithMap({stage, group, items, scope}) {
  const apply = () => group.setItems(lockedItems(items, stage.dataset.mapState === "unavailable"));
  if (typeof MutationObserver === "function") {  // node tests stub the DOM without it
    const watch = new MutationObserver(apply);
    watch.observe(stage, {attributes: true, attributeFilter: ["data-map-state"]});
    scope.onDispose(() => watch.disconnect());
  }
  apply();
}
