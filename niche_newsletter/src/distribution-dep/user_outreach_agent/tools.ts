import { z } from "zod";
import assert, { AssertionError } from "node:assert";
import { tool } from "@langchain/core/tools";
import { ApifyClient } from "apify-client";
import { getNotionMCP } from "../../shared/notion_mcp.js";

// Workflow: search popular pages via the general instagram scraper -> load them to Notion
// get their followers who are engaging with their contents (check comments) -> load them to Notion
// manager checks the list of possible leads -> if approved, agent sends a DM

const KEEP_NOTION_TOOLS = new Set([
    "notion-search",
    "notion-fetch",
    "notion-create-pages",
    "notion-update-page",
    "notion-move-pages",
    "notion-duplicate-page",
    "notion-create-database",
    "notion-update-data-source",
    "notion-create-view",
    "notion-update-view",
]);

// One versatile actor covers all three cases below — which content it returns is
// picked with `resultsType` ("details" | "posts" | "comments"), not by actor choice.
const INSTAGRAM_ACTOR = "apify/instagram-scraper";

function getApifyClient(): ApifyClient | null {
    const token = process.env.APIFY_API_KEY;
    if (!token) {
        console.warn("No api key has been set for Apify tool");
        return null;
    }
    return new ApifyClient({ token });
}

function toProfileUrl(usernameOrUrl: string): string {
    return usernameOrUrl.includes("instagram.com")
        ? usernameOrUrl
        : `https://www.instagram.com/${usernameOrUrl}/`;
}

function toPostUrl(idOrUrl: string): string {
    return idOrUrl.includes("instagram.com")
        ? idOrUrl
        : `https://www.instagram.com/p/${idOrUrl}/`;
}

interface InstagramProfileDetails {
    username: string;
    followersCount?: number;
    [key: string]: unknown;
}

interface InstagramPost {
    id: string;
    url: string;
    shortCode: string;
    caption?: string;
    likesCount?: number;
    commentsCount?: number;
    timestamp?: string;
    [key: string]: unknown;
}

interface InstagramComment {
    ownerUsername?: string;
    ownerProfilePicUrl?: string;
    text?: string;
    timestamp?: string;
    [key: string]: unknown;
}

const scrapePopularPagePosts = tool(
    async ({ keywords, profilesPerKeyword = 50, minFollowers = 10000, postsPerPage = 8 }) => {
        const client = getApifyClient();
        if (!client) {
            return "APIFY_API_KEY is not set — cannot scrape Instagram.";
        }
        assert(profilesPerKeyword <= 100, "The number of profiles fetched must be lower or equal than 100!")
        assert(postsPerPage <= 12, "The number of retrieved posts per profile page must be lower or equal than 12!")

        let profiles: InstagramProfileDetails[];
        try {
            const perKeyword = await Promise.all(keywords.map(async (keyword) => {
                const run = await client.actor(INSTAGRAM_ACTOR).call({
                    resultsType: "details",
                    search: keyword,
                    searchType: "profile",
                    searchLimit: profilesPerKeyword,
                });
                const { items } = await client.dataset<InstagramProfileDetails>(run.defaultDatasetId).listItems();
                return items;
            }));

            // The same account can surface for more than one keyword — dedupe by username.
            const seen = new Set<string>();
            profiles = perKeyword.flat().filter((profile) => {
                if (seen.has(profile.username)) return false;
                seen.add(profile.username);
                return true;
            });
        } catch (error) {
            return `Failed to search Instagram profiles: ${error}`;
        }

        // Only pages past the follower threshold are worth spending post-scraping
        // budget on — assert the invariant per page rather than crashing the whole
        // batch when one requested page doesn't clear the bar.
        const qualifying: InstagramProfileDetails[] = [];
        for (const profile of profiles) {
            try {
                assert(
                    typeof profile.followersCount === "number" && profile.followersCount > minFollowers,
                    `@${profile.username} has ${profile.followersCount ?? "an unknown number of"} followers — below the ${minFollowers} threshold`
                );
                qualifying.push(profile);
            } catch (error) {
                if (!(error instanceof AssertionError)) throw error;
                console.warn(error.message);
            }
        }

        if (qualifying.length === 0) {
            return "None of the given accounts have more than the required follower count — no posts scraped.";
        }

        try {
            const results = await Promise.all(qualifying.map(async (profile) => {
                const run = await client.actor(INSTAGRAM_ACTOR).call({
                    resultsType: "posts",
                    directUrls: [toProfileUrl(profile.username)],
                    resultsLimit: postsPerPage,
                });
                const { items: posts } = await client.dataset<InstagramPost>(run.defaultDatasetId).listItems();
                return {
                    username: profile.username,
                    followersCount: profile.followersCount,
                    posts: posts.map((post) => ({
                        id: post.id,
                        url: post.url,
                        shortCode: post.shortCode,
                        caption: post.caption,
                        likesCount: post.likesCount,
                        commentsCount: post.commentsCount,
                        timestamp: post.timestamp,
                    })),
                };
            }));
            return JSON.stringify(results);
        } catch (error) {
            return `Failed to scrape posts for qualifying pages: ${error}`;
        }
    }, {
        name: "scrape_popular_page_posts",
        description: "Search Instagram for profiles matching the given keywords, keep only pages with more than a follower threshold (default 10000), then scrape a few recent posts from each qualifying page. Returns, per qualifying page, its follower count and posts (id, url, shortCode, caption, likesCount, commentsCount, timestamp).",
        schema: z.object({
            keywords: z.array(z.string()).min(1)
                .describe("Search terms to discover Instagram profiles by, e.g. 'ai newsletter' or 'productivity coach'"),
            profilesPerKeyword: z.number().int().positive().optional().default(10)
                .describe("Max profiles to discover per keyword (default 10)"),
            minFollowers: z.number().int().positive().optional().default(10000)
                .describe("Minimum follower count a page must have to qualify (default 10000)"),
            postsPerPage: z.number().int().positive().optional().default(5)
                .describe("Number of recent posts to fetch per qualifying page (default 5)"),
        }),
    }
);

const getPostComments = tool(
    async ({ postIds, commentsPerPost = 20 }) => {
        const client = getApifyClient();
        if (!client) {
            return "APIFY_API_KEY is not set — cannot scrape Instagram.";
        }

        try {
            const results = await Promise.all(postIds.map(async (postId) => {
                const run = await client.actor(INSTAGRAM_ACTOR).call({
                    resultsType: "comments",
                    directUrls: [toPostUrl(postId)],
                    resultsLimit: commentsPerPost,
                });
                const { items } = await client.dataset<InstagramComment>(run.defaultDatasetId).listItems();
                return {
                    postId,
                    comments: items.map((comment) => ({
                        user: {
                            username: comment.ownerUsername,
                            profilePicUrl: comment.ownerProfilePicUrl,
                        },
                        comment: comment.text,
                        timestamp: comment.timestamp,
                    })),
                };
            }));
            return JSON.stringify(results);
        } catch (error) {
            return `Failed to scrape post comments: ${error}`;
        }
    }, {
        name: "get_post_comments",
        description: "Fetch comments — commenter user info plus comment text — for the given Instagram posts. Accepts post shortCodes/ids (as returned by scrape_popular_page_posts) or full post URLs.",
        schema: z.object({
            postIds: z.array(z.string()).min(1)
                .describe("Instagram post shortCodes/ids (e.g. 'DLNsnpUTdVS') or full post URLs"),
            commentsPerPost: z.number().int().positive().optional().default(20)
                .describe("Max comments to fetch per post (default 20)"),
        }),
    }
);

// const apifyTools = await getApifyTools();
const notionTools = await getNotionMCP(KEEP_NOTION_TOOLS);
export const outreachTools = [scrapePopularPagePosts, getPostComments, ...notionTools];
