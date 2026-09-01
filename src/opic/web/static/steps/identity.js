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

  // Lo que se guarda y cuánto, aquí y no en un enlace: es la pantalla donde se
  // piden el nombre y el correo, así que es el único sitio donde el aviso
  // llega antes de que se den. Del audio se promete sólo lo que es verdad —
  // que el fichero no sale de este ordenador —; la transcripción sí viaja al
  // corrector, y decir "nada sale de aquí" sería mentira.
  const retention = document.createElement("p");
  retention.className = "closing-note";
  retention.textContent =
    "녹음 파일은 이 컴퓨터를 벗어나지 않으며, 채점이 끝나 리포트가 만들어지면 바로 삭제됩니다. " +
    "이름과 이메일, 답변 전사본, 채점 결과는 30일 뒤에 함께 삭제됩니다.";

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

  // Antes de los campos y no debajo del botón: el aviso sólo sirve si se lee
  // antes de escribir el nombre.
  form.append(heading, note, retention, nameLabel, emailLabel, submit, status);

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
