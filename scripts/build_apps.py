import json

# (num, name, category, hint_raw, hint_url_or_None, hint_type, note_or_None)
rows = [
(1,"Salesforce","CRM and Sales","salesforce.com","https://salesforce.com","domain",None),
(2,"HubSpot","CRM and Sales","hubspot.com","https://hubspot.com","domain",None),
(3,"Pipedrive","CRM and Sales","pipedrive.com","https://pipedrive.com","domain",None),
(4,"Attio","CRM and Sales","attio.com","https://attio.com","domain",None),
(5,"Twenty","CRM and Sales","twenty.com (open-source CRM)","https://twenty.com","note","open-source CRM"),
(6,"Podio","CRM and Sales","podio.com","https://podio.com","domain",None),
(7,"Zoho CRM","CRM and Sales","zoho.com/crm","https://zoho.com/crm","domain",None),
(8,"Close","CRM and Sales","close.com","https://close.com","domain",None),
(9,"Copper","CRM and Sales","copper.com","https://copper.com","domain",None),
(10,"DealCloud","CRM and Sales","api.docs.dealcloud.com","https://api.docs.dealcloud.com","docs_url",None),

(11,"Zendesk","Support and Helpdesk","zendesk.com","https://zendesk.com","domain",None),
(12,"Intercom","Support and Helpdesk","intercom.com","https://intercom.com","domain",None),
(13,"Freshdesk","Support and Helpdesk","freshdesk.com","https://freshdesk.com","domain",None),
(14,"Front","Support and Helpdesk","front.com","https://front.com","domain",None),
(15,"Pylon","Support and Helpdesk","usepylon.com","https://usepylon.com","domain",None),
(16,"LiveAgent","Support and Helpdesk","liveagent.com","https://liveagent.com","domain",None),
(17,"Plain","Support and Helpdesk","plain.com","https://plain.com","domain",None),
(18,"Help Scout","Support and Helpdesk","helpscout.com","https://helpscout.com","domain",None),
(19,"Gorgias","Support and Helpdesk","gorgias.com","https://gorgias.com","domain",None),
(20,"Gladly","Support and Helpdesk","gladly.com","https://gladly.com","domain",None),

(21,"Slack","Communications and Messaging","slack.com","https://slack.com","domain",None),
(22,"Twilio","Communications and Messaging","twilio.com","https://twilio.com","domain",None),
(23,"Zoho Cliq","Communications and Messaging","zoho.com/cliq","https://zoho.com/cliq","domain",None),
(24,"Lark (Larksuite)","Communications and Messaging","open.larksuite.com","https://open.larksuite.com","docs_url",None),
(25,"Pumble","Communications and Messaging","pumble.com","https://pumble.com","domain",None),
(26,"Discord","Communications and Messaging","discord.com","https://discord.com","domain",None),
(27,"Telegram","Communications and Messaging","core.telegram.org","https://core.telegram.org","docs_url",None),
(28,"WhatsApp Business","Communications and Messaging","developers.facebook.com/docs/whatsapp","https://developers.facebook.com/docs/whatsapp","docs_url",None),
(29,"Aircall","Communications and Messaging","aircall.io","https://aircall.io","domain",None),
(30,"Vonage","Communications and Messaging","developer.vonage.com","https://developer.vonage.com","docs_url",None),

(31,"Google Ads","Marketing, Ads, Email and Social","developers.google.com/google-ads","https://developers.google.com/google-ads","docs_url",None),
(32,"Meta Ads","Marketing, Ads, Email and Social","developers.facebook.com/docs/marketing-apis","https://developers.facebook.com/docs/marketing-apis","docs_url",None),
(33,"LinkedIn Ads","Marketing, Ads, Email and Social","learn.microsoft.com/linkedin/marketing","https://learn.microsoft.com/linkedin/marketing","docs_url",None),
(34,"GoHighLevel","Marketing, Ads, Email and Social","highlevel.stoplight.io","https://highlevel.stoplight.io","docs_url",None),
(35,"Mailchimp","Marketing, Ads, Email and Social","mailchimp.com/developer","https://mailchimp.com/developer","docs_url",None),
(36,"Klaviyo","Marketing, Ads, Email and Social","developers.klaviyo.com","https://developers.klaviyo.com","docs_url",None),
(37,"systeme.io","Marketing, Ads, Email and Social","systeme.io (funnel builder)","https://systeme.io","note","funnel builder"),
(38,"Pinterest","Marketing, Ads, Email and Social","developers.pinterest.com","https://developers.pinterest.com","docs_url",None),
(39,"Threads (Meta)","Marketing, Ads, Email and Social","developers.facebook.com/docs/threads","https://developers.facebook.com/docs/threads","docs_url",None),
(40,"SendGrid","Marketing, Ads, Email and Social","sendgrid.com","https://sendgrid.com","domain",None),

(41,"Shopify","Ecommerce","shopify.dev","https://shopify.dev","docs_url",None),
(42,"WooCommerce","Ecommerce","woocommerce.com/document/woocommerce-rest-api","https://woocommerce.com/document/woocommerce-rest-api","docs_url",None),
(43,"BigCommerce","Ecommerce","developer.bigcommerce.com","https://developer.bigcommerce.com","docs_url",None),
(44,"Salesforce Commerce Cloud","Ecommerce","developer.salesforce.com/docs/commerce","https://developer.salesforce.com/docs/commerce","docs_url",None),
(45,"Magento (Adobe Commerce)","Ecommerce","developer.adobe.com/commerce","https://developer.adobe.com/commerce","docs_url",None),
(46,"Squarespace","Ecommerce","developers.squarespace.com","https://developers.squarespace.com","docs_url",None),
(47,"Ecwid","Ecommerce","api-docs.ecwid.com","https://api-docs.ecwid.com","docs_url",None),
(48,"Gumroad","Ecommerce","gumroad.com/api","https://gumroad.com/api","docs_url",None),
(49,"Amazon Selling Partner","Ecommerce","developer-docs.amazon.com/sp-api","https://developer-docs.amazon.com/sp-api","docs_url",None),
(50,"fanbasis","Ecommerce","fanbasis.com","https://fanbasis.com","domain",None),

(51,"DataForSEO","Data, SEO and Scraping","docs.dataforseo.com","https://docs.dataforseo.com","docs_url",None),
(52,"SE Ranking","Data, SEO and Scraping","seranking.com/api","https://seranking.com/api","docs_url",None),
(53,"Ahrefs","Data, SEO and Scraping","ahrefs.com/api","https://ahrefs.com/api","docs_url",None),
(54,"MrScraper","Data, SEO and Scraping","docs.mrscraper.com","https://docs.mrscraper.com","docs_url",None),
(55,"Apify","Data, SEO and Scraping","docs.apify.com","https://docs.apify.com","docs_url",None),
(56,"Firecrawl","Data, SEO and Scraping","firecrawl.dev","https://firecrawl.dev","domain",None),
(57,"Bright Data","Data, SEO and Scraping","brightdata.com","https://brightdata.com","domain",None),
(58,"Sherlock","Data, SEO and Scraping","github.com/sherlock-project/sherlock","https://github.com/sherlock-project/sherlock","docs_url",None),
(59,"Waterfall.io","Data, SEO and Scraping","waterfall.io (contact/company intel)","https://waterfall.io","note","contact/company intel"),
(60,"Clay","Data, SEO and Scraping","clay.com","https://clay.com","domain",None),

(61,"GitHub","Developer, Infra and Data platforms","docs.github.com/rest","https://docs.github.com/rest","docs_url",None),
(62,"Vercel","Developer, Infra and Data platforms","vercel.com/docs/rest-api","https://vercel.com/docs/rest-api","docs_url",None),
(63,"Netlify","Developer, Infra and Data platforms","docs.netlify.com/api","https://docs.netlify.com/api","docs_url",None),
(64,"Cloudflare","Developer, Infra and Data platforms","developers.cloudflare.com/api","https://developers.cloudflare.com/api","docs_url",None),
(65,"Supabase","Developer, Infra and Data platforms","supabase.com/docs","https://supabase.com/docs","docs_url",None),
(66,"Neo4j","Developer, Infra and Data platforms","neo4j.com/docs/api","https://neo4j.com/docs/api","docs_url",None),
(67,"Snowflake","Developer, Infra and Data platforms","docs.snowflake.com","https://docs.snowflake.com","docs_url",None),
(68,"MongoDB Atlas","Developer, Infra and Data platforms","mongodb.com/docs/atlas/api","https://mongodb.com/docs/atlas/api","docs_url",None),
(69,"Datadog","Developer, Infra and Data platforms","docs.datadoghq.com/api","https://docs.datadoghq.com/api","docs_url",None),
(70,"Sentry","Developer, Infra and Data platforms","docs.sentry.io/api","https://docs.sentry.io/api","docs_url",None),

(71,"Notion","Productivity and Project Management","developers.notion.com","https://developers.notion.com","docs_url",None),
(72,"Airtable","Productivity and Project Management","airtable.com/developers","https://airtable.com/developers","docs_url",None),
(73,"Linear","Productivity and Project Management","developers.linear.app","https://developers.linear.app","docs_url",None),
(74,"Jira","Productivity and Project Management","developer.atlassian.com","https://developer.atlassian.com","docs_url",None),
(75,"Asana","Productivity and Project Management","developers.asana.com","https://developers.asana.com","docs_url",None),
(76,"Monday.com","Productivity and Project Management","developer.monday.com","https://developer.monday.com","docs_url",None),
(77,"ClickUp","Productivity and Project Management","clickup.com/api","https://clickup.com/api","docs_url",None),
(78,"Coda","Productivity and Project Management","coda.io/developers","https://coda.io/developers","docs_url",None),
(79,"Smartsheet","Productivity and Project Management","smartsheet.com/developers","https://smartsheet.com/developers","docs_url",None),
# Harvest: URL clarification only; EXTRA_SEED_DOMAINS seeds harvestapp.com + getharvest.com; HINT_FIELD_MAP empty.
(80,"Harvest","Productivity and Project Management","harvestapp.com (help.getharvest.com/api-v2)","https://help.getharvest.com/api-v2","note","primary domain harvestapp.com; docs at help.getharvest.com/api-v2"),

(81,"Stripe","Finance and Fintech","stripe.com/docs/api","https://stripe.com/docs/api","docs_url",None),
(82,"Plaid","Finance and Fintech","plaid.com/docs","https://plaid.com/docs","docs_url",None),
(83,"Binance","Finance and Fintech","binance-docs.github.io","https://binance-docs.github.io","docs_url",None),
# Paygent: hint_url null, empty domain seeds, unconstrained Call 1; high unknown expected. No slug heuristics.
(84,"Paygent Connect","Finance and Fintech","paygent (NMI-powered)",None,"note","NMI-powered; no URL given in the brief"),
(85,"iPayX","Finance and Fintech","ipayx.ai/docs","https://ipayx.ai/docs","docs_url",None),
(86,"QuickBooks","Finance and Fintech","developer.intuit.com","https://developer.intuit.com","docs_url",None),
(87,"Xero","Finance and Fintech","developer.xero.com","https://developer.xero.com","docs_url",None),
(88,"Brex","Finance and Fintech","developer.brex.com","https://developer.brex.com","docs_url",None),
(89,"Ramp","Finance and Fintech","docs.ramp.com","https://docs.ramp.com","docs_url",None),
(90,"PitchBook","Finance and Fintech","pitchbook.com (research API)","https://pitchbook.com","note","research API"),

(91,"NotebookLM","AI, Research and Media-native","cloud.google.com/gemini (Enterprise API)","https://cloud.google.com/gemini","note","Enterprise API"),
(92,"Otter AI","AI, Research and Media-native","help.otter.ai (MCP server)","https://help.otter.ai","note","MCP server"),
(93,"Fathom","AI, Research and Media-native","fathom.video","https://fathom.video","domain",None),
(94,"Consensus","AI, Research and Media-native","consensus.app (OAuth requested)","https://consensus.app","note","OAuth requested"),
(95,"Reducto","AI, Research and Media-native","reducto.ai (document parsing)","https://reducto.ai","note","document parsing"),
(96,"Devin","AI, Research and Media-native","docs.devin.ai (MCP)","https://docs.devin.ai","note","MCP"),
(97,"higgsfield","AI, Research and Media-native","higgsfield.ai/cli (content suite)","https://higgsfield.ai/cli","note","content suite"),
(98,"Mermaid CLI","AI, Research and Media-native","github.com/mermaid-js/mermaid-cli","https://github.com/mermaid-js/mermaid-cli","docs_url",None),
(99,"YouTube Transcript","AI, Research and Media-native","transcriptapi.com","https://transcriptapi.com","domain",None),
(100,"Grain","AI, Research and Media-native","grain.com (meeting notes)","https://grain.com","note","meeting notes"),
]

apps = []
for num, name, cat, hint_raw, hint_url, hint_type, note in rows:
    apps.append({
        "id": num,
        "app_name": name,
        "category": cat,
        "hint_raw": hint_raw,
        "hint_url": hint_url,
        "hint_type": hint_type,
        "hint_note": note,
    })

assert len(apps) == 100, len(apps)
assert len({a["id"] for a in apps}) == 100
assert len({a["app_name"] for a in apps}) == 100

with open("/home/claude/spec/apps_100.json", "w") as f:
    json.dump(apps, f, indent=2)

TEN = ["Notion","Firecrawl","Meta Ads","DealCloud","Twenty","Shopify","Ahrefs","Zendesk","Stripe","fanbasis"]
subset = [a for a in apps if a["app_name"] in TEN]
assert len(subset) == 10, [a["app_name"] for a in subset]
with open("/home/claude/spec/apps_10.json", "w") as f:
    json.dump(subset, f, indent=2)

from collections import Counter
print("total:", len(apps))
print("by hint_type:", dict(Counter(a["hint_type"] for a in apps)))
print("by category:", dict(Counter(a["category"] for a in apps)))
print("null hint_url:", [a["app_name"] for a in apps if a["hint_url"] is None])
print("subset ok:", [a["app_name"] for a in subset])
