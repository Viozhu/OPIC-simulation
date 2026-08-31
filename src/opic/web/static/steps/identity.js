// Paso 0 — quién se examina. No es un registro: el correo es la etiqueta con
// la que este examen se encuentra después, en la hoja de cálculo y en la
// consola. No se verifica y no se le envía nada.
export async function render(state, {api, show}) {
  const form = document.createElement("form");

  const heading = document.createElement("h2");
  heading.textContent = "시작하기 전에";

  const note = document.createElement("p");
  note.textContent =
    "결과 리포트를 찾을 때 사용합니다. 확인 메일은 보내지 않습니다.";

  const nameLabel = document.createElement("label");
  const name = document.createElement("input");
  name.type = "text";
  name.name = "name";
  name.required = true;
  name.autocomplete = "name";
  name.maxLength = 200;
  nameLabel.append("이름 ", name);

  const emailLabel = document.createElement("label");
  const email = document.createElement("input");
  email.type = "email";
  email.name = "email";
  email.required = true;
  email.autocomplete = "email";
  email.maxLength = 200;
  emailLabel.append("이메일 ", email);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "다음";

  const status = document.createElement("p");
  status.className = "issues";

  form.append(heading, note, nameLabel, emailLabel, submit, status);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = "";
    const data = new FormData(form);
    try {
      await show(
        await api.send("PUT", `/api/sessions/${state.id}/identity`, {
          name: String(data.get("name")),
          email: String(data.get("email")),
        }),
      );
    } catch (error) {
      // 422 trae `issues` con el coreano ya escrito por el servidor; cualquier
      // otra cosa es la red.
      const issues = error.payload?.issues;
      status.textContent = issues?.length
        ? issues.map((issue) => issue.message_ko).join(" ")
        : "서버와 연결할 수 없습니다. 다시 시도해 주세요.";
      submit.disabled = false;
    }
  });

  document.getElementById("app").replaceChildren(form);
}
