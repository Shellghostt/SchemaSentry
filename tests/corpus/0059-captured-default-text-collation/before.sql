CREATE TABLE ss_m3_0059.parent (id text PRIMARY KEY);
CREATE TABLE ss_m3_0059.child (id integer, parent_id text, CONSTRAINT child_fk FOREIGN KEY (parent_id) REFERENCES ss_m3_0059.parent(id));
CREATE INDEX support ON ss_m3_0059.child (parent_id);
