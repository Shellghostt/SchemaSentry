CREATE TABLE ss_m3_0033."parent" ("a" integer, "b" integer, CONSTRAINT "parent_pkey" PRIMARY KEY (a,b));
CREATE TABLE ss_m3_0033."child" ("a" integer, "b" integer, CONSTRAINT "child_fk" FOREIGN KEY (a, b) REFERENCES ss_m3_0033.parent(a, b));
CREATE INDEX "support" ON ss_m3_0033."child" (b, a);
