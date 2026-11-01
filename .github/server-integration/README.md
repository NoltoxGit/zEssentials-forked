# Server integration (NoltoxGit fork only)

`integration/server` combines the current `develop` branch with every other branch on this fork, except `main` and `integration/server` itself. It is the default branch of this fork so its scheduled workflow can run. It is not intended for an upstream pull request.

The workflow checks for changes approximately every five minutes. It rebuilds the combined tree from the current branch tips, including after a branch is deleted or rebased, and builds the plugin before publishing a normal fast-forward commit. It never pushes to source branches or rewrites published history.

The `zEssentials-server` artifact in a successful **Server integration** run contains the compiled plugin JAR. Use **Run workflow** to request a fresh build without waiting for a source change. zMenu 1.1.2.1 or later is required on the server.

Make application changes on the source branches. Direct application edits to this generated branch are replaced during the next integration. Only the workflow and files in this directory are preserved as integration-specific configuration.

If a merge conflict or compilation error occurs, the existing server branch is kept and the workflow fails. Resolve the conflict deliberately rather than selecting an entire branch's version. `resolutions.json` records both sides and the reviewed result of the current changelog overlap. A resolution is reused only when the conflict contents match exactly; new conflicts still stop the update.
