import { DropboxResponseError, type Dropbox } from "dropbox";

function toDirectDropboxUrl(shareUrl: string): string {
    const url = new URL(shareUrl);
    url.searchParams.delete("dl");
    url.searchParams.set("raw", "1");
    return url.toString();
}

export async function uploadToDropboxAndGetShareUrl(dropbox: Dropbox, path: string, contents: Buffer): Promise<string> {

    let uploadedPath: string;
    try {
        const uploadResult = await dropbox.filesUpload({
            path,
            contents,
            mode: { '.tag': 'overwrite' },
            mute: true,
        });
        uploadedPath = uploadResult.result.path_lower ?? path;
    } catch (error) {
        throw new Error(`Dropbox upload failed: ${error}`);
    }

    try {
        const shareResult = await dropbox.sharingCreateSharedLinkWithSettings({
            path: uploadedPath,
            settings: { audience: { '.tag': 'public' } },
        });
        return toDirectDropboxUrl(shareResult.result.url);
    } catch (error) {
        const existingUrl = (error instanceof DropboxResponseError
            ? (error.error as { shared_link_already_exists?: { metadata?: { url?: string } } })?.shared_link_already_exists?.metadata?.url
            : undefined);
        if (!existingUrl) throw new Error(`Dropbox share-link creation failed: ${error}`);
        return toDirectDropboxUrl(existingUrl);
    }
}