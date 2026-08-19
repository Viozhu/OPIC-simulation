// Step 1 — Background Survey. The Korean text comes from /api/survey, never
// from this file: `core/survey.py` is the single source for what it says.
export async function render(state, {api, show}) {
  const schema = await api.get("/api/survey");
  const form = document.createElement("form");
  const chosen = new Set();

  form.append(
    radioGroup("occupation", "현재 귀하는 어느 분야에 종사하고 계십니까?", schema.occupations),
    radioGroup("is_student", "현재 학생이십니까?", [
      {id: "yes", label_ko: "예"},
      {id: "no", label_ko: "아니오"},
    ]),
    radioGroup("recent_course", "최근 어떤 강의를 수강했습니까?", schema.recent_courses),
    radioGroup("housing", "현재 귀하는 어디에 살고 계십니까?", schema.housing),
  );

  const counter = document.createElement("p");
  counter.className = "counter";
  const updateCounter = () => {
    counter.textContent = `선택한 항목: ${chosen.size} / ${schema.min_total_items}`;
    counter.classList.toggle("short", chosen.size < schema.min_total_items);
    submit.disabled = chosen.size < schema.min_total_items;
  };

  for (const group of schema.groups) {
    const box = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = `${group.label_ko} (${group.minimum}개 이상)`;
    box.append(legend);
    for (const item of group.items) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = item.id;
      input.addEventListener("change", () => {
        input.checked ? chosen.add(item.id) : chosen.delete(item.id);
        updateCounter();
      });
      label.append(input, ` ${item.label_ko}`);
      box.append(label);
    }
    form.append(box);
  }

  const issues = document.createElement("ul");
  issues.className = "issues";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "다음";

  form.append(counter, issues, submit);
  updateCounter();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    issues.replaceChildren();
    const data = new FormData(form);
    try {
      const next = await api.send("PUT", `/api/sessions/${state.id}/survey`, {
        occupation: data.get("occupation"),
        is_student: data.get("is_student") === "yes",
        housing: data.get("housing"),
        selected_item_ids: [...chosen],
        recent_course: data.get("is_student") === "yes" ? null : data.get("recent_course"),
      });
      await show(next);
    } catch (error) {
      for (const issue of error.payload?.issues ?? [{error: "unknown", detail: ""}]) {
        const line = document.createElement("li");
        line.textContent = `${issue.error} ${issue.detail}`;
        issues.append(line);
      }
      submit.disabled = false;
    }
  });

  document.getElementById("app").append(form);
}

function radioGroup(name, question, options) {
  const box = document.createElement("fieldset");
  const legend = document.createElement("legend");
  legend.textContent = question;
  box.append(legend);
  options.forEach((option, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = name;
    input.value = option.id;
    input.required = true;
    if (index === 0) input.checked = true;
    label.append(input, ` ${option.label_ko}`);
    box.append(label);
  });
  return box;
}
