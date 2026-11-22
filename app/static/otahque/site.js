// Otahque's script for every page (Chapter 28).

// Tell the server this browser's time zone. The cookie is
// a display preference: the server checks it is a real
// zone name, and a member's profile zone comes first.
const browserZone = Intl.DateTimeFormat()
  .resolvedOptions().timeZone;
if (browserZone) {
  document.cookie = 'otahque_tz=' + browserZone
    + '; path=/; max-age=31536000; samesite=lax';
}

// Close a message. The server has already used it up;
// this only hides it on the page in front of you.
for (const button of
     document.querySelectorAll('[data-close]')) {
  button.addEventListener('click', () => {
    button.closest('.alert').remove();
  });
}
