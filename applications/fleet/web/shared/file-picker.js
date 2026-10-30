// D-926 C7: the native file input stays invisible, so the chosen file name is shown beside the picker button.
document.addEventListener('change', event => {
  const input = event.target;
  if (!input.matches?.('.file-picker > input[type="file"]')) return;
  const name = input.parentElement.querySelector('[data-file-name]');
  if (name) name.textContent = input.files[0]?.name || '선택한 파일 없음';
});
