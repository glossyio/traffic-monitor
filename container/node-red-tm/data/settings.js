/**
 * Node-RED Settings, refer to documentation:
 *    https://nodered.org/docs/user-guide/runtime/settings-file
 **/

const crypto = require("crypto");

// The reverse proxy logs people in. For an admin, it sends each editor request a short-lived token from
// tm-control (NodeRedToken in tm-control/backend/tm_control/core/auth.py):
//   base64url(JSON {"u", "r", "exp"}) "." base64url(HMAC-SHA256(key, first part)), without "=" padding.
// Returns the editor user for a valid admin token, and null for anything else. Without a key, no token is valid.
const BASE64URL = /^[A-Za-z0-9_-]+$/;

function verifyProxyToken(token, key, nowSeconds) {
  if (typeof token !== "string" || typeof key !== "string" || key === "") {
    return null;
  }
  const parts = token.split(".");
  if (parts.length !== 2 || !BASE64URL.test(parts[0]) || !BASE64URL.test(parts[1])) {
    return null;
  }
  const [body, signature] = parts;
  const expected = Buffer.from(crypto.createHmac("sha256", key).update(body, "ascii").digest("base64url"));
  const given = Buffer.from(signature);
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) {
    return null;
  }
  let claims;
  try {
    claims = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  } catch (err) {
    return null;
  }
  if (
    claims === null ||
    typeof claims !== "object" ||
    typeof claims.u !== "string" ||
    typeof claims.r !== "string" ||
    typeof claims.exp !== "number" ||
    !Number.isFinite(claims.exp) ||
    claims.exp <= nowSeconds ||
    claims.r !== "admin"
  ) {
    return null;
  }
  return { username: claims.u, permissions: "*" };
}

module.exports = {
  flowFile: "flows.json",
  credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET,
  flowFilePretty: true,

  // No editor users of its own: the editor accepts only the proxy's token (see verifyProxyToken above).
  // TM_NR_TOKEN_KEY comes from node-red-tm.env, and without it every request is refused.
  adminAuth: {
    type: "credentials",
    users: [],
    tokenHeader: "x-tm-nr-token",
    tokens: (token) =>
      Promise.resolve(verifyProxyToken(token, process.env.TM_NR_TOKEN_KEY || "", Date.now() / 1000)),
  },

  uiPort: process.env.PORT || 1880,

  diagnostics: {
    enabled: true,
    ui: true,
  },
  runtimeState: {
    enabled: false,
    ui: false,
  },

  logging: {
    console: {
      level: "info",
      metrics: false,
      audit: false,
    },
  },

  contextStorage: {
    default: {
      module:"memory",
    }
  },

  exportGlobalContextKeys: false,

  externalModules: {
  },

  editorTheme: {
    header: {
      // This is the text next to the Node-red logo on the editor page header
      title: process.env.TM_HOSTNAME,
    },
    page: {
      // And this is the text next to the favicon on the browser tab
      title: process.env.TM_HOSTNAME,
    },
    palette: {
    },
    projects: {
      enabled: true,
      workflow: {
        mode: "manual",
      },
    },

    codeEditor: {
      lib: "monaco",
      options: {
      },
    },
    markdownEditor: {
      mermaid: {
        enabled: true,
      },
    },

    multiplayer: {
      enabled: false,
    },
    tours: false,
    // Logging in and out happens in tm-control, so hide the editor's own user menu
    userMenu: false,
  },

  functionExternalModules: true,

  functionTimeout: 0,

  functionGlobalContext: {
    fs:require('fs'),
    path:require('path')
  },

  debugMaxLength: 1000,

  mqttReconnectTime: 15000,

  serialReconnectTime: 15000,

};

module.exports.verifyProxyToken = verifyProxyToken;
