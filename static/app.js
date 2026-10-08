(() => {
  const doctorInput = document.querySelector('input[name="doctor_id"]');
  if (!doctorInput) return;

  const storageKey = "clinic-antiviral.doctor-id";
  if (!doctorInput.value) {
    doctorInput.value = window.localStorage.getItem(storageKey) || "";
  }

  document.querySelectorAll('form input[name="doctor_id"]').forEach((input) => {
    input.form?.addEventListener("submit", () => {
      if (input.value) window.localStorage.setItem(storageKey, input.value);
    });
  });
})();

(() => {
  const operatorInputs = document.querySelectorAll('input[name="operator"]');
  if (!operatorInputs.length) return;
  const storageKey = "clinic-antiviral.operator-id";
  const remembered = window.localStorage.getItem(storageKey) || "";
  operatorInputs.forEach((input) => {
    if (!input.value) input.value = remembered;
    input.form?.addEventListener("submit", () => {
      if (input.value) window.localStorage.setItem(storageKey, input.value);
    });
  });
})();
