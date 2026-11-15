CREATE TABLE ss_m3_0031.parent (id integer NOT NULL PRIMARY KEY);
CREATE TABLE ss_m3_0031."child" ("id" integer NOT NULL, "parent_id" integer, CONSTRAINT "child_fk" FOREIGN KEY (parent_id) REFERENCES ss_m3_0031.parent(id));
