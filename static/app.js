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
