// Choose the browser's time zone when none is chosen yet.
const field = document.getElementById('id_timezone');
const zone = Intl.DateTimeFormat()
  .resolvedOptions().timeZone;
const known = field && [...field.options]
  .some((option) => option.value === zone);
if (known && !field.value) {
  field.value = zone;
}
