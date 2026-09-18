import { getBufferTools, getCanvaTools } from "./mcp.js";

const canvaTools = await getCanvaTools();
const bufferTools = await getBufferTools();

export const SMTools = [...canvaTools, ...bufferTools];