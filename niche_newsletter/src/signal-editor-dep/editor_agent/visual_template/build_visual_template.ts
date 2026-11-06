import { Template, defaultBuildLogger } from "e2b";

const template = Template()
  .fromNodeImage("24")
  .setWorkdir("/home/user")
  .copy("src/signal-editor-dep/editor_agent/visual_template/package.json", "package.json")
  .copy("src/signal-editor-dep/editor_agent/visual_template/tsconfig.json", "tsconfig.json")
  .npmInstall();

await Template.build(template, "newsletter-visual-gen", {
  onBuildLogs: defaultBuildLogger(),
});
