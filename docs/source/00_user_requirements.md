# Source: customer requirement messages

Verbatim, in order. These four messages are the requirement source of truth;
everything the assistant produced is derived from them.

<!-- BEGIN SOURCE -->

## Message 1 (2019 chars)

customer is planning to build a website where courses can be purchased. customer might want to go with a payment gateway integration such as payfast or netcash, or direct eft deposit with local banks. would like to plan to develop such a backend and frontend for them. there should be a advanced LMS system also included after the purchase, the customer is then provided login credentials. there is an option of a paid service where they can request one-on-one training in a live workshop using either external google meet, MS teams or Zoom interface. there should be an option to generate certificates from the company after they have completed. they must not be able to bypass the training by just clicking next, there should be proper checks and controls in place. to motivate them, there should also be badges and progress they can share via linkedIn, similar to what coursera does. there should be RBAC and ABAC in place. there will need for different views/roles for the end customer, possibly tiered approach, depending on the type of package they buy, this should be built to do individual training, and for group type training. the backend view from the administrator should have the ability to view high level statuses, deep analytics using a online AI cloud provider of their choosing through use use of API integration to do some analytics on the staff based on certain testing, surveys done. the training involves leadership type training, think gartner, and other business schools that does excecutive type training. and also to do engagement training etc. the scope can change. there should be a billing/invoicing/CRM system inplace that would allow for the user to manage and control the billing side. on the CRM side, think a marketing aspect is needed where they could send out bulk emails. monthly newsletters should also be available. do a deep dive on the features, functionalities and the technology stack, deployment and security requirements to deploy something like this on a cloud environment.


## Message 2 (1002 chars)

once done, create a phased approach, come up with some design and view concepts, the proposed workflow, and possibly if we can have a full ecosystem for android and IOS apps. the company also has internal marketing collateral and podcasts that we can possible include somewhere in the frontend as a lure for them to lead them into a sale, there could be free content that users can view to get a sense, possible give them "guest and test" credentials, but they must provide information in the signup that would allow it to be captured to try to convert them later.the phases/gates must be developed and planned in such a way that after each stage a visible view of the app can be seen to showcase features and functionality. think we can store the content in a static bucket, depending on the customers hosting preference, build in capabilites of either using S3 buckets, or a microsoft hosting bucket. for the information captured, the database should be salted and hashed in the case of a compromise.


## Message 3 (2467 chars)

Is the primary market South Africa only or international? - both
What currencies and tax rules are required? - for local, south african Tax rules, international, USD costing but local TAX rules
Is VAT registration applicable? > the company is fully registered, and the system should fully be auditable for compliance
Are recurring subscriptions required? > this is an option
Are corporate customers expected to pay by invoice/EFT? >yes, and potentially a Purchase order
Do enterprise customers require SSO? > maybe we can allow the system to be customised. there are big customers, and maybe they should have their own unique login like "company1.executivetrainingportal.co.za"? the content can be also uniquely catered and created for them
Is SCORM/xAPI required?
Should certificates be accredited or CPD-related? > this is an option, plan for this.
Are surveys anonymous? > techinically no, but the feature could be included when each survey is created/crafted
Can managers see individual learner results?> they can get high level overview, but not specifics. to avoid bullying, this feature can be enabled by the system administrator depending on the course
Is AI analysis allowed to process personal data, or must it be anonymized? > anonymised
Which AI provider is preferred? > please add the top 4 such as openAI, claude, and gemini, copilot
What level of video protection is required? > industry standard
Is DRM required?. yes, to avoid the content from being scraped or downloaded, depending on if the administrator allows downloading and is only linked to a certain customer
Which meeting provider is preferred by facilitators? > MS Teams at this moment, but should be open to use other external systems
Should the platform support multiple facilitators and scheduling? > yes
Is there an existing CRM/accounting system? > I dont think so.
Do they need email marketing built-in or integrated? both
What is the expected number of learners? > starting from ~ 50 to 500
What is the expected number of concurrent users/videos? say 100 users for now. the system should have analytics such as clicks, site visits, what the users are interested in etc. this could then be shown or reported on the administrator dashboard
What is the desired data residency? > south africa
What is the budget and launch timeline? TBA
Who will create content? the administrator and owners
Is there existing video content? Yes
Is there a brand/design system? TBA


## Message 4 (432 chars)

1. create a complete technical solution document for the developers/site administrators first. Think we should start off with a lean approach on the infrastructure, and then look at scaling, dont want to over provision the hardware as this could inflate costing when the platform is only starting off, dont want the revenue to be eaten up by the infrastructure costing too soon.
 2. draft the Feature matrix /pricing tier document.

