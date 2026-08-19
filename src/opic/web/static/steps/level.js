// Step 2 — Self Assessment. Choosing here is what fixes the difficulty of the
// question set, and it is what starts the generation running in the background.
export async function render(state, {api, show}) {
  const {options} = await api.get("/api/levels");
  const form = document.createElement("form");
  const box = document.createElement("fieldset");
  const legend = document.createElement("legend");
  legend.textContent = "본인의 영어 말하기 수준을 선택해 주세요.";
  box.append(legend);

  options.forEach((option) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "level";
    input.value = String(option.level);
    input.required = true;
    label.append(input, ` ${option.level}. ${option.description_ko}`);
    box.append(label);
  });

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "다음";
  const status = document.createElement("p");
  status.className = "issues";
  form.append(box, submit, status);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = "";
    const level = Number(new FormData(form).get("level"));
    try {
      await show(await api.send("PUT", `/api/sessions/${state.id}/level`, {level}));
    } catch (error) {
      status.textContent = "서버와 연결할 수 없습니다. 다시 시도해 주세요.";
      submit.disabled = false;
    }
  });

  document.getElementById("app").append(form);
}
