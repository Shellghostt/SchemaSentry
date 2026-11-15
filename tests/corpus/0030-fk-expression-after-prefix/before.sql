CREATE TABLE ss_m3_0030.parent (id integer NOT NULL PRIMARY KEY);
CREATE TABLE ss_m3_0030."child" ("id" integer NOT NULL, "parent_id" integer, CONSTRAINT "child_fk" FOREIGN KEY (parent_id) REFERENCES ss_m3_0030.parent(id));
CREATE INDEX "support" ON ss_m3_0030."child" (parent_id, (id + 1));
