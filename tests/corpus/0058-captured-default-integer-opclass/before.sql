CREATE TABLE ss_m3_0058.parent (id integer PRIMARY KEY);
CREATE TABLE ss_m3_0058.child (id integer, parent_id integer, CONSTRAINT child_fk FOREIGN KEY (parent_id) REFERENCES ss_m3_0058.parent(id));
CREATE INDEX support ON ss_m3_0058.child (parent_id);
