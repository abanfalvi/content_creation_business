import { Template, defaultBuildLogger } from "e2b";

// Need rebuild when package json files change
const scheduledTemplate = Template()
  .fromNodeImage("22")
  .setWorkdir("/home/user")
  .copy("./package.json", "package.json")
  .copy("./package-lock.json", "package-lock.json")
  .npmInstall();

await Template.build(scheduledTemplate, "newsletter-scheduled-run", {
  onBuildLogs: defaultBuildLogger(),
});
