import { useEffect, useState } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";

import { APP_NAME } from "../../branding";

/**
 * Two small pieces of installed-app plumbing that have no other home.
 *
 * 1. A new version is waiting. The service worker has already downloaded the
 *    new bundle but will not activate it while tabs are open on the old one.
 *    Without a prompt, a professor keeps running whatever frontend was cached
 *    the first time they installed the app -- which surfaces as API calls
 *    failing in ways the backend logs cannot explain. 'prompt' is used rather
 *    than 'autoUpdate' deliberately: reloading on its own would discard a
 *    half-finished scan.
 *
 * 2. Connectivity. In a browser tab a dead connection is obvious from the
 *    error page. Installed full-screen with no address bar, it is not, and an
 *    upload that fails because the phone dropped off the campus Wi-Fi looks
 *    identical to one the server rejected.
 */
export default function PWAUpdatePrompt() {
  const [offline, setOffline] = useState(!navigator.onLine);

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisterError(error) {
      // Almost always the certificate. Browsers refuse to register a service
      // worker on an origin with a certificate error, and the page keeps
      // working normally, so the failure is otherwise invisible.
      console.warn(
        "Service worker registration failed. The app still works, but it " +
          "cannot be installed or cached offline. This usually means the " +
          "site is served over HTTPS with an untrusted (self-signed) " +
          "certificate.",
        error
      );
    },
  });

  useEffect(() => {
    const goOnline = () => setOffline(false);
    const goOffline = () => setOffline(true);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  if (!needRefresh && !offline) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-center p-4">
      <div className="pointer-events-auto w-full max-w-md rounded-xl bg-[#462776] px-4 py-3 text-white shadow-lg">
        {offline ? (
          <p className="text-sm">
            You are offline. {APP_NAME} needs a connection to scan and grade —
            anything you upload now will fail until you reconnect.
          </p>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm">A new version is ready.</p>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={() => setNeedRefresh(false)}
                className="rounded-lg px-3 py-1.5 text-sm underline underline-offset-2"
              >
                Later
              </button>
              <button
                type="button"
                onClick={() => updateServiceWorker(true)}
                className="rounded-lg bg-white px-3 py-1.5 text-sm font-semibold text-[#462776]"
              >
                Reload
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
