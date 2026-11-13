{
  "name": "{{NPM_PACKAGE_NAME}}",
  "version": "0.1.0",
  "description": "{{PROJECT_DESCRIPTION_EN}}",
  "type": "module",
  "private": true,
  "engines": {
    "node": ">={{NODE_LTS_MAJOR}}"
  },
  "scripts": {
    "lint": "node --check src/index.js",
    "test": "node --test",
    "build": "node --check src/index.js",
    "start": "node src/index.js"
  }
}
