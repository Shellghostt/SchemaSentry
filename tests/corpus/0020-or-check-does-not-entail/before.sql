CREATE TABLE ss_m3_0020."items" ("id" integer NOT NULL, "body" text, CONSTRAINT "proof" CHECK (body IS NOT NULL OR id > 0));
INSERT INTO ss_m3_0020.items VALUES (1, NULL);
