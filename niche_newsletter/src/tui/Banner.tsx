import { Box, Text } from "ink";
import figlet from "figlet";

const APP_NAME = "NICHE NEWSLETTER";
const LOGO_LINES = figlet.textSync(APP_NAME, { font: "Small" }).replace(/\n+$/, "").split("\n");

export function Banner() {
    return (
        <Box flexDirection="column">
            {LOGO_LINES.map((line, index) => (
                <Text key={index} color="cyan" bold wrap="truncate-end">{line}</Text>
            ))}
        </Box>
    );
}
