/**
 * Node-RED Settings, refer to documentation:
 *    https://nodered.org/docs/user-guide/runtime/settings-file
 **/

module.exports = {
  flowFile: "flows.json",
  credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET,
  flowFilePretty: true,

  adminAuth: {
    type: "credentials",
    users: [
      {
        username: "admin",
        password:
          "$2a$08$zZWtXTja0fB1pzD4sHCMyOCMYz2Z6dNbM6tl8sJogENOMcxWV9DN.",
        permissions: "*",
      },
    ],
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
  },

  functionExternalModules: true,

  functionTimeout: 0,

  functionGlobalContext: {
  },

  debugMaxLength: 1000,

  mqttReconnectTime: 15000,

  serialReconnectTime: 15000,

};
