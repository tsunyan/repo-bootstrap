export function main() {
  return "{{PROJECT_NAME}}";
}

if (process.argv[1]?.endsWith("index.js")) {
  console.log(main());
}
