import { Box, Text } from "ink";
import { Banner } from "./Banner.js";

type HomeProps = {
    threadId: string;
    model: string;
    version: string;
    cwd: string;
};

export function Home({ threadId, model, version, cwd }: HomeProps) {
    return (
        <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1} marginBottom={1}>
            <Banner />
            <Text dimColor wrap="truncate-end">Chat with the content-creation orchestrator</Text>

            <Box marginTop={1} flexDirection="column">
                <Text bold color="cyan">Session</Text>
                <Text wrap="truncate-end"><Text color="gray">Thread     </Text>{threadId}</Text>
                <Text wrap="truncate-end"><Text color="gray">Model      </Text>{model}</Text>
                <Text wrap="truncate-end"><Text color="gray">Version    </Text>{version}</Text>
                <Text wrap="truncate-end"><Text color="gray">Directory  </Text>{cwd}</Text>
            </Box>

            <Box marginTop={1} flexDirection="column">
                <Text bold color="cyan">Commands</Text>
                <Text dimColor wrap="truncate-end">  Enter    send message</Text>
                <Text dimColor wrap="truncate-end">  /exit    quit</Text>
                <Text dimColor wrap="truncate-end">  Ctrl+C   quit</Text>
            </Box>
        </Box>
    );
}
