package com.mazel.esthetic.mapper;

import com.mazel.esthetic.dto.CollectionLogDto;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.List;

@Mapper
public interface CollectionLogMapper {

    List<CollectionLogDto> selectRecentLogs(@Param("limit") int limit);

    CollectionLogDto selectLatestByType(@Param("sourceName") String sourceName);

    int insertLog(CollectionLogDto dto);
}
