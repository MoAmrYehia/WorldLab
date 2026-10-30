// GitHub Pages settings. The Python server (accounts, crop planning, live seasons) runs elsewhere,
// for example on a Hugging Face Space. Put its address here; leave it empty for a showcase-only site.
// If the server can't be reached, the site falls back to the landing page and a recorded season.
(function () {
  var SERVER = "https://moamryehia-worldlab.hf.space";
  var up = /\/app\/[^/]*$/.test(location.pathname) ? "../" : "";
  window.WORLDLAB = {
    api: SERVER,
    home: up || "./", login: up + "login.html", signup: up + "signup.html",
    app: up + "app/", demo: up + "app/?demo",
  };
})();
