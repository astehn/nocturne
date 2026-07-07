CREATE TABLE IF NOT EXISTS contributions (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  name            VARCHAR(120)  DEFAULT NULL,
  email           VARCHAR(190)  DEFAULT NULL,
  target          VARCHAR(190)  DEFAULT NULL,
  integration     VARCHAR(80)   DEFAULT NULL,
  notes           TEXT          DEFAULT NULL,
  orig_filename   VARCHAR(255)  NOT NULL,
  stored_filename VARCHAR(120)  NOT NULL,
  size_bytes      BIGINT        NOT NULL,
  ip              VARCHAR(45)   DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS downloads (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip         VARCHAR(45)  DEFAULT NULL,
  user_agent VARCHAR(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
