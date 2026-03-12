// Neuter the Fullscreen API so game websites cannot go fullscreen.
// This runs at document_start before any page scripts execute.
(function () {
  Element.prototype.requestFullscreen = function () {
    return Promise.resolve();
  };
  // Webkit prefix (older Chrome)
  Element.prototype.webkitRequestFullscreen = function () {
    return Promise.resolve();
  };
  Element.prototype.webkitRequestFullScreen = function () {
    return Promise.resolve();
  };
  // Make it look like fullscreen is never active
  Object.defineProperty(document, "fullscreenElement", {
    get: function () {
      return null;
    },
  });
  Object.defineProperty(document, "webkitFullscreenElement", {
    get: function () {
      return null;
    },
  });
  Object.defineProperty(document, "fullscreenEnabled", {
    get: function () {
      return false;
    },
  });
  document.exitFullscreen = function () {
    return Promise.resolve();
  };
  document.webkitExitFullscreen = function () {};
})();
